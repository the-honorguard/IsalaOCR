from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template, request, send_file

from .projects import resolve_project_workspace
from .db import MISSING_MARKERS, TrainingDatabase, VALID_OCR_CONTENT_FILTERS


def _optional_confidence(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    parsed = float(value)
    if parsed < 0 or parsed > 1:
        raise ValueError("Confidence must be between 0 and 1")
    return parsed


def _filter_args() -> dict[str, str | None]:
    # Opening the UI without filters starts in the useful review queue:
    # pending, non-empty OCR predictions below 80% confidence.
    if not request.args:
        return {
            "status": "pending",
            "field": None,
            "min_confidence": None,
            "max_confidence": "0.8",
            "ocr_content": "text",
        }
    return {
        "status": request.args.get("status") or None,
        "field": request.args.get("field") or None,
        "min_confidence": request.args.get("min_confidence") or None,
        "max_confidence": request.args.get("max_confidence") or None,
        "ocr_content": request.args.get("ocr_content") or "all",
    }


def create_label_app(workspace: str | Path) -> Flask:
    root = resolve_project_workspace(workspace).resolve()
    database = TrainingDatabase(root / "samples.sqlite3")
    app = Flask(__name__, template_folder="templates")
    app.config.update(SECRET_KEY="local-only-no-session-state")

    def safe_crop(sample: dict) -> Path:
        path = (root / str(sample["crop_path"])).resolve()
        if root not in path.parents or not path.is_file():
            abort(404)
        return path

    def value_counts() -> dict[str, int]:
        """Count only samples that are eligible for value review."""
        with database.connect() as db:
            rows = db.execute(
                """
                SELECT status, COUNT(*) AS amount
                FROM samples
                WHERE roi_review_status='correct'
                GROUP BY status
                """
            ).fetchall()
        counts = {
            "pending": 0,
            "accepted": 0,
            "no_value": 0,
            "unreadable": 0,
            "excluded": 0,
        }
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["amount"])
        counts["total"] = sum(counts.values())
        counts["reviewed"] = counts["total"] - counts["pending"]
        return counts

    def query_samples(
        filters: dict[str, str | None],
        *,
        limit: int,
        offset: int = 0,
        exclude_sample_id: str | None = None,
    ):
        ocr_content = str(filters.get("ocr_content") or "all")
        if ocr_content not in VALID_OCR_CONTENT_FILTERS:
            abort(400)
        try:
            min_confidence = _optional_confidence(filters.get("min_confidence"))
            max_confidence = _optional_confidence(filters.get("max_confidence"))
        except ValueError:
            abort(400)
        return database.list_samples(
            status=filters.get("status"),
            field_key=filters.get("field"),
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            ocr_content=ocr_content,
            roi_review_status="correct",
            exclude_sample_id=exclude_sample_id,
            limit=limit,
            offset=offset,
        )

    @app.get("/")
    def dashboard():
        filters = _filter_args()
        try:
            page = max(int(request.args.get("page", "1")), 1)
        except ValueError:
            abort(400)
        per_page = 60
        samples = query_samples(filters, limit=per_page, offset=(page - 1) * per_page)
        return render_template(
            "dashboard.html",
            counts=value_counts(),
            fields=database.fields(),
            samples=samples,
            selected_status=filters["status"],
            selected_field=filters["field"],
            selected_min_confidence=filters["min_confidence"],
            selected_max_confidence=filters["max_confidence"],
            selected_ocr_content=filters["ocr_content"],
            page=page,
        )

    @app.get("/crop/<sample_id>")
    def crop(sample_id: str):
        sample = database.get(sample_id)
        if not sample:
            abort(404)
        return send_file(safe_crop(sample), mimetype="image/png", max_age=0)

    @app.get("/sample/<sample_id>")
    def sample(sample_id: str):
        current = database.get(sample_id)
        if not current or current["roi_review_status"] != "correct":
            abort(404)
        filters = _filter_args()
        candidates = query_samples(filters, limit=10000)
        ids = [item["sample_id"] for item in candidates]
        try:
            index = ids.index(sample_id)
        except ValueError:
            index = -1
        previous_id = ids[index - 1] if index > 0 else None
        next_id = ids[index + 1] if 0 <= index < len(ids) - 1 else None
        return render_template(
            "sample.html",
            sample=current,
            previous_id=previous_id,
            next_id=next_id,
            filters=filters,
            counts=value_counts(),
        )

    @app.post("/sample/<sample_id>")
    def review(sample_id: str):
        current = database.get(sample_id)
        if not current or current["roi_review_status"] != "correct":
            abort(404)

        filters = {
            "status": request.form.get("status_filter") or None,
            "field": request.form.get("field_filter") or None,
            "min_confidence": request.form.get("min_confidence_filter") or None,
            "max_confidence": request.form.get("max_confidence_filter") or None,
            "ocr_content": request.form.get("ocr_content_filter") or "all",
        }
        candidates_before = query_samples(filters, limit=10000)
        ids_before = [item["sample_id"] for item in candidates_before]
        preferred_next = None
        if sample_id in ids_before:
            position = ids_before.index(sample_id)
            if position + 1 < len(ids_before):
                preferred_next = ids_before[position + 1]

        action = request.form.get("action", "value_save")
        notes = request.form.get("notes", "")
        exact_label = request.form.get("exact_label", "")
        if action in {"value_correct", "ocr_correct"}:
            database.review(
                sample_id, "accepted", str(current["raw_ocr"]), notes, content_class="value"
            )
        elif action in {"value_save", "save"}:
            database.review(
                sample_id, "accepted", exact_label, notes, content_class="value"
            )
        elif action == "placeholder":
            if exact_label == "":
                abort(400)
            database.review(
                sample_id,
                "accepted",
                exact_label,
                notes,
                content_class="placeholder",
            )
        elif action == "no_value":
            database.review(
                sample_id, "no_value", None, notes, content_class="no_value"
            )
        elif action in {"unreadable", "excluded", "pending"}:
            database.review(sample_id, action, None, notes)
        else:
            abort(400)

        # Re-query after saving. A reviewed pending sample no longer matches the
        # pending queue, and exclude_sample_id is a final guard against loops.
        next_id = None
        if preferred_next:
            preferred = database.get(preferred_next)
            if preferred and preferred["sample_id"] != sample_id:
                still_visible = query_samples(filters, limit=10000, exclude_sample_id=sample_id)
                visible_ids = {item["sample_id"] for item in still_visible}
                if preferred_next in visible_ids:
                    next_id = preferred_next
        if not next_id:
            remaining = query_samples(
                filters, limit=1, exclude_sample_id=sample_id
            )
            next_id = remaining[0]["sample_id"] if remaining else None

        query = urlencode(
            {key: value for key, value in filters.items() if value and value != "all"}
        )
        if next_id:
            suffix = f"?{query}" if query else ""
            return redirect(f"/sample/{next_id}{suffix}")
        return redirect(f"/{'?' + query if query else ''}")

    @app.get("/health")
    def health():
        return {"ok": True, "counts": value_counts()}

    return app


def serve_labeler(workspace: str | Path, host: str = "127.0.0.1", port: int = 8088) -> None:
    try:
        from waitress import serve
    except ImportError as exc:
        raise RuntimeError("The training labeler requires the 'training' optional dependencies") from exc
    app = create_label_app(workspace)
    serve(app, host=host, port=port, threads=4)
