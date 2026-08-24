from __future__ import annotations

from pathlib import Path

from flask import abort, flash, redirect, render_template, request, url_for

from .db import TrainingDatabase
from .projects import resolve_project_workspace
from .recognition_ground_truth import EXTRACTION_METHOD, recognition_gt_counts


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

    @app.before_request
    def redirect_recognition_review_process_step():
        if request.path in {"/process/recognition-gt", "/process/recognition-review", "/process/recognition-gt-studio"}:
            return redirect(url_for("recognition_gt_review_home"))
        return None

    @app.get("/recognition-gt-review")
    def recognition_gt_review_home():
        database = current_database()
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
        )
