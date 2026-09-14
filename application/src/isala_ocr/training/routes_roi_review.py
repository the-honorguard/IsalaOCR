"""ROI-review routes, split out of webui.create_web_app.

Same pattern as routes_documents.register_document_routes: the handlers
move here, but the helpers they depend on (``source_rows``,
``source_samples``, ``roi_review_counts``, the active project
``database`` proxy and ``workspace_root``) stay in webui.py because
other route groups there also depend on them, and are passed in
explicitly instead of re-implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, flash, redirect, render_template, request, url_for


def register_roi_review_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    source_rows: Callable[[], list[dict[str, Any]]],
    source_samples: Callable[[str], list[dict[str, Any]]],
    roi_review_counts: Callable[[], dict[str, int]],
) -> None:
    @app.get("/roi-review")
    def roi_review_home():
        status = str(request.args.get("status", "all")).strip().lower()
        if status not in {"all", "pending", "correct", "incorrect", "deferred"}:
            abort(400)
        sources = source_rows()
        counts_by_source = database.roi_review_status_counts_by_source()
        for source in sources:
            source["roi_counts"] = counts_by_source.get(
                str(source["source_id"]),
                {"pending": 0, "correct": 0, "incorrect": 0, "deferred": 0},
            )
        roi_counts = roi_review_counts()
        return render_template(
            "roi_review.html", sources=sources, roi_counts=roi_counts, selected_status=status,
            header_counts={"total": roi_counts["total"], "pending": roi_counts["pending"] + roi_counts["deferred"], "accepted": roi_counts["correct"]},
            header_total_label="ROI's", header_pending_label="niet afgerond",
            header_accepted_label="correct",
        )

    @app.route("/roi-review/<source_id>", methods=["GET", "POST"])
    def roi_review_document(source_id: str):
        samples = [
            sample for sample in source_samples(source_id)
            if str(sample.get("extraction_method") or "") != "mapped_generic_stale"
        ]
        if not samples:
            abort(404)
        if request.method == "POST":
            for sample in samples:
                sid = sample["sample_id"]
                status = str(request.form.get(f"roi_status_{sid}", "keep"))
                notes = str(request.form.get(f"roi_notes_{sid}", ""))
                if status == "keep":
                    continue
                database.review_roi(sid, status, notes)
            flash("ROI-beoordeling voor deze DICOM is opgeslagen.", "success")
            return redirect(url_for("roi_review_document", source_id=source_id))
        return render_template(
            "roi_review_document.html", source_id=source_id, samples=samples,
            image_width=samples[0]["image_width"], image_height=samples[0]["image_height"],
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            header_counts={
                "total": len(samples),
                "pending": sum(1 for sample in samples if sample["roi_review_status"] in {"pending", "deferred"}),
                "accepted": sum(1 for sample in samples if sample["roi_review_status"] == "correct"),
            },
            header_total_label="ROI's", header_pending_label="niet afgerond",
            header_accepted_label="correct",
        )
