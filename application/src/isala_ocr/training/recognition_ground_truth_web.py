from __future__ import annotations

from pathlib import Path

from urllib.parse import urlencode

from flask import abort, flash, redirect, render_template, request, url_for

from .db import TrainingDatabase
from .projects import resolve_project_workspace
from .recognition_ground_truth import (
    EXTRACTION_METHOD,
    recognition_gt_counts,
    recognition_scope,
    recognition_scope_options,
    recognition_scope_preview,
    save_recognition_scope,
)


def install_recognition_ground_truth_review(app, workspace: str | Path) -> None:
    workspace_root = Path(workspace)

    def current_database() -> TrainingDatabase:
        project_workspace = resolve_project_workspace(workspace_root)
        return TrainingDatabase(project_workspace / "samples.sqlite3")

    def source_rows(database: TrainingDatabase, status_filter: str = "", sort: str = "source") -> list[dict]:
        where = "WHERE extraction_method=?"
        params: list[str] = [EXTRACTION_METHOD]
        if status_filter:
            where += " AND status=?"
            params.append(status_filter)
        order_by = "source_id"
        if sort == "errors":
            order_by = "pending DESC, excluded DESC, source_id"
        elif sort == "pending":
            order_by = "pending DESC, source_id"
        with database.connect() as db:
            rows = db.execute(
                f"""
                SELECT source_id,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted,
                       SUM(CASE WHEN status IN ('unreadable','excluded','no_value') THEN 1 ELSE 0 END) AS excluded
                FROM samples
                {where}
                GROUP BY source_id
                ORDER BY {order_by}
                """,
                params,
            ).fetchall()
        return [
            {
                "source_id": str(row["source_id"]),
                "total": int(row["total"] or 0),
                "pending": int(row["pending"] or 0),
                "accepted": int(row["accepted"] or 0),
                "excluded": int(row["excluded"] or 0),
            }
            for row in rows
        ]

    def source_samples(database: TrainingDatabase, source_id: str) -> list[dict]:
        with database.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM samples
                WHERE source_id=? AND extraction_method=?
                ORDER BY roi_y1, roi_x1, sample_id
                """,
                (source_id, EXTRACTION_METHOD),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_samples(database: TrainingDatabase, status_filter: str = "") -> list[dict]:
        where = "WHERE extraction_method=?"
        params: list[str] = [EXTRACTION_METHOD]
        if status_filter:
            where += " AND status=?"
            params.append(status_filter)
        with database.connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM samples
                {where}
                ORDER BY source_id, roi_y1, roi_x1, sample_id
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    @app.before_request
    def redirect_recognition_review_process_step():
        if request.path in {"/process/recognition-gt", "/process/recognition-review", "/process/recognition-gt-studio"}:
            return redirect(url_for("recognition_gt_review_home"))
        return None

    @app.get("/recognition-gt-review")
    def recognition_gt_review_home():
        database = current_database()
        project_root = resolve_project_workspace(workspace_root)
        counts = recognition_gt_counts(database)
        status_filter = str(request.args.get("status") or "").strip().lower()
        if status_filter not in {"pending", "accepted", "excluded", "unreadable", "no_value"}:
            status_filter = ""
        sort = str(request.args.get("sort") or "source").strip().lower()
        if sort not in {"source", "pending", "errors"}:
            sort = "source"
        return render_template(
            "recognition_gt_review.html",
            sources=source_rows(database, status_filter, sort),
            counts=counts,
            status_filter=status_filter,
            sort=sort,
            header_counts=counts,
            header_total_label="Recognition samples",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
        )

    @app.route("/recognition-gt-review/<source_id>", methods=["GET", "POST"])
    def recognition_gt_review_document(source_id: str):
        database = current_database()
        samples = source_samples(database, source_id)
        if not samples:
            abort(404)

        if request.method == "POST":
            global_action = str(request.form.get("global_action") or "").strip().lower()
            changed = 0
            for sample in samples:
                sample_id = str(sample["sample_id"])
                action = str(request.form.get(f"status_{sample_id}") or "keep").strip().lower()
                exact = str(request.form.get(f"label_{sample_id}") or sample.get("raw_ocr") or "")
                notes = str(request.form.get(f"notes_{sample_id}") or "")
                if global_action == "accept_all_ocr" and str(sample.get("status") or "") == "pending":
                    exact = str(sample.get("raw_ocr") or "")
                    # A truly blank cell has nothing for a text recognizer to
                    # learn. Keep '-' / '–' / '—' as literal text, but exclude
                    # empty strings from the recognition dataset.
                    action = "accepted" if exact != "" else "excluded"
                    if action == "excluded" and not notes:
                        notes = "Lege crop: geen recognitionlabel"
                if action == "keep":
                    continue
                if action == "accepted":
                    # Recognition GT is verbatim. A lone '-', '–' or '—' is a
                    # legitimate literal label here and is NOT converted to null.
                    if exact == "":
                        database.review(sample_id, "excluded", None, notes or "Lege crop: geen recognitionlabel")
                    else:
                        database.review(sample_id, "accepted", exact, notes, "value")
                elif action in {"unreadable", "excluded", "pending"}:
                    database.review(sample_id, action, None, notes)
                else:
                    abort(400)
                changed += 1
            flash(f"Recognition-GT opgeslagen: {changed} wijziging(en).", "success")
            return redirect(url_for("recognition_gt_review_document", source_id=source_id))

        counts = {
            "total": len(samples),
            "pending": sum(str(item.get("status") or "") == "pending" for item in samples),
            "accepted": sum(str(item.get("status") or "") == "accepted" for item in samples),
        }
        return render_template(
            "recognition_gt_review_document.html",
            source_id=source_id,
            samples=samples,
            counts=counts,
            header_counts=counts,
            header_total_label="crops",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
            recognition_scope=recognition_scope(project_root),
            recognition_scope_options=recognition_scope_options(project_root),
            recognition_scope_preview=recognition_scope_preview(project_root),
        )

    @app.get("/recognition-scope")
    def recognition_scope_home():
        project_root = resolve_project_workspace(workspace_root)
        return render_template(
            "recognition_scope.html",
            recognition_scope=recognition_scope(project_root),
            recognition_scope_options=recognition_scope_options(project_root),
            recognition_scope_preview=recognition_scope_preview(project_root),
        )

    @app.post("/recognition-gt-scope")
    def recognition_gt_scope_save():
        project_root = resolve_project_workspace(workspace_root)
        tables: dict[str, dict[str, list[int]]] = {}
        for value in request.form.getlist("scope_row"):
            table, separator, row = str(value).partition("|")
            if not separator:
                continue
            try:
                tables.setdefault(table, {"rows": [], "columns": []})["rows"].append(int(row))
            except ValueError:
                continue
        for value in request.form.getlist("scope_column"):
            table, separator, column = str(value).partition("|")
            if not separator:
                continue
            try:
                tables.setdefault(table, {"rows": [], "columns": []})["columns"].append(int(column))
            except ValueError:
                continue
        save_recognition_scope(project_root, tables)
        flash("Recognition-scope opgeslagen. Vernieuw daarna de Recognition samples.", "success")
        return redirect(url_for("recognition_gt_review_home"))

    @app.route("/recognition-gt-review/sample/<sample_id>", methods=["GET", "POST"])
    def recognition_gt_review_sample(sample_id: str):
        database = current_database()
        status_filter = str(request.values.get("status") or "").strip().lower()
        if status_filter not in {"pending", "accepted", "excluded", "unreadable", "no_value"}:
            status_filter = ""

        samples = all_samples(database, status_filter)
        current = next((item for item in samples if item["sample_id"] == sample_id), None)
        if current is None:
            # A sample remains reviewable when it is no longer in the active
            # filter (for example after accepting a pending item).
            current = next((item for item in all_samples(database) if item["sample_id"] == sample_id), None)
        if current is None:
            abort(404)

        if request.method == "POST":
            action = str(request.form.get("action") or "").strip().lower()
            exact = str(request.form.get("exact_label") or "")
            notes = str(request.form.get("notes") or "")
            if action == "accept_model":
                exact = str(current.get("raw_ocr") or "")
                action = "accepted"
            if action == "accepted":
                if exact == "":
                    database.review(sample_id, "excluded", None, notes or "Lege crop: geen recognitionlabel")
                else:
                    database.review(sample_id, "accepted", exact, notes, "value")
            elif action in {"unreadable", "excluded", "pending"}:
                database.review(sample_id, action, None, notes)
            else:
                abort(400)

            # Continue in the same queue. Prefer the next item, then the
            # previous one, and finally return to the overview.
            ids = [str(item["sample_id"]) for item in samples]
            index = ids.index(sample_id) if sample_id in ids else -1
            next_id = ids[index + 1] if index >= 0 and index + 1 < len(ids) else None
            previous_id = ids[index - 1] if index > 0 else None
            target = next_id or previous_id
            if target:
                query = urlencode({"status": status_filter}) if status_filter else ""
                return redirect(url_for("recognition_gt_review_sample", sample_id=target) + (f"?{query}" if query else ""))
            return redirect(url_for("recognition_gt_review_home", status=status_filter) if status_filter else url_for("recognition_gt_review_home"))

        # Recompute after the fallback lookup so navigation reflects the
        # visible queue and not a stale source-page result.
        ids = [str(item["sample_id"]) for item in samples]
        index = ids.index(sample_id) if sample_id in ids else -1
        previous_id = ids[index - 1] if index > 0 else None
        next_id = ids[index + 1] if index >= 0 and index + 1 < len(ids) else None
        return render_template(
            "recognition_gt_review_sample.html",
            sample=current,
            previous_id=previous_id,
            next_id=next_id,
            status_filter=status_filter,
            counts=recognition_gt_counts(database),
            source_url=url_for("recognition_gt_review_document", source_id=current["source_id"]),
            header_counts=recognition_gt_counts(database),
            header_total_label="Recognition samples",
            header_pending_label="te beoordelen",
            header_accepted_label="goedgekeurd",
        )
