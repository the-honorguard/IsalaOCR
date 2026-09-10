"""Legacy manual value-review routes, split out of webui.create_web_app.

Same pattern as the other ``routes_*`` modules split out of ``webui.py``:
the handlers move here, but the helpers they depend on
(``value_source_rows``, ``value_source_samples``,
``value_in_configured_range``, ``value_review_counts``,
``query_samples``, ``filter_args`` and the active project ``database``
proxy) stay in webui.py - ``value_review_counts`` and ``query_samples``
are also used by the still-inline ``/sample/<sample_id>`` and
``/review/queue`` routes - and are passed in explicitly.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from .db import MISSING_MARKERS


def register_value_review_routes(
    app: Flask,
    *,
    database: Any,
    filter_args: Callable[[], dict[str, str | None]],
    query_samples: Callable[..., list[dict[str, Any]]],
    value_source_rows: Callable[[], list[dict[str, Any]]],
    value_source_samples: Callable[[str], list[dict[str, Any]]],
    value_in_configured_range: Callable[[dict[str, Any]], bool],
    value_review_counts: Callable[[], dict[str, int]],
) -> None:
    @app.get("/review")
    def review_home():
        return redirect(url_for("process_step", step_key="value-review"))

        # Legacy manual value-review route retained below for old links/jobs.
        sources = value_source_rows()
        counts = value_review_counts()
        pending = database.list_samples(
            status="pending", roi_review_status="correct", min_confidence=0.995,
            ocr_content="text", limit=100000
        )
        smart = [sample for sample in pending if value_in_configured_range(sample)]
        return render_template(
            "review.html", sources=sources, smart_count=len(smart), value_counts=counts,
            header_counts=counts, header_total_label="waarden",
            header_pending_label="te beoordelen", header_accepted_label="goedgekeurd",
        )

    @app.route("/review/document/<source_id>", methods=["GET", "POST"])
    def review_document(source_id: str):
        if request.method == "GET" and request.args.get("legacy") != "1":
            return redirect(url_for("process_step", step_key="value-review"))
        samples = value_source_samples(source_id)
        if not samples:
            flash(
                "Deze DICOM heeft nog geen definitief goedgekeurde ROI's voor waardenbeoordeling.",
                "warning",
            )
            return redirect(url_for("review_home"))
        if request.method == "POST":
            global_action = request.form.get("global_action", "")
            for sample in samples:
                sid = sample["sample_id"]
                action = request.form.get(f"status_{sid}", "keep")
                label = request.form.get(f"label_{sid}", sample["raw_ocr"])
                notes = request.form.get(f"notes_{sid}", "")
                if global_action == "accept_all_ocr" and sample["status"] == "pending":
                    action = "accepted"
                    label = sample["raw_ocr"]
                if action == "keep":
                    continue
                if action == "accepted":
                    database.review(sid, "accepted", label, notes, "value")
                elif action == "placeholder":
                    database.review(sid, "accepted", label, notes, "placeholder")
                elif action in {"no_value", "unreadable", "excluded", "pending"}:
                    database.review(sid, action, None, notes)
                else:
                    abort(400)
            flash("Waardenbeoordeling voor deze DICOM is opgeslagen.", "success")
            return redirect(url_for("review_document", source_id=source_id))
        counts = {
            "total": len(samples),
            "pending": sum(1 for sample in samples if sample["status"] == "pending"),
            "accepted": sum(1 for sample in samples if sample["status"] == "accepted"),
        }
        return render_template(
            "review_document.html", source_id=source_id, samples=samples,
            header_counts=counts, header_total_label="waarden",
            header_pending_label="te beoordelen", header_accepted_label="goedgekeurd",
        )

    @app.post("/review/smart-apply")
    def smart_apply():
        threshold = max(0.80, min(1.0, float(request.form.get("threshold", "0.98"))))
        qa = max(0, min(50, int(request.form.get("qa_percent", "10"))))
        pending = database.list_samples(
            status="pending", roi_review_status="correct", limit=100000
        )
        accepted = 0
        retained = 0
        for sample in pending:
            text = str(sample["raw_ocr"])
            eligible = (
                text.strip() not in ("", *MISSING_MARKERS)
                and sample["raw_confidence"] >= threshold
                and value_in_configured_range(sample)
            )
            if not eligible:
                continue
            bucket = int(hashlib.sha256(sample["sample_id"].encode()).hexdigest()[:8], 16) % 100
            if bucket < qa:
                retained += 1
                continue
            database.review(
                sample["sample_id"], "accepted", text,
                "Smart review: high-confidence exact OCR", "value",
            )
            accepted += 1
        flash(
            f"{accepted} hoge-confidence waarden goedgekeurd; "
            f"{retained} als kwaliteitssteekproef behouden.",
            "success",
        )
        return redirect(url_for("review_home"))

    @app.post("/review/duplicates-apply")
    def duplicates_apply():
        with database.connect() as db:
            rows = db.execute(
                """
                SELECT p.sample_id, a.exact_label, a.content_class
                FROM samples p JOIN samples a
                  ON p.crop_sha256=a.crop_sha256 AND p.field_key=a.field_key
                WHERE p.status='pending' AND p.roi_review_status='correct'
                  AND p.crop_sha256<>''
                  AND a.status='accepted' AND a.roi_review_status='correct'
                  AND a.exact_label IS NOT NULL
                """
            ).fetchall()
        done = 0
        seen = set()
        for row in rows:
            if row["sample_id"] in seen:
                continue
            database.review(
                row["sample_id"], "accepted", row["exact_label"],
                "Overgenomen van pixel-identieke goedgekeurde crop", row["content_class"],
            )
            seen.add(row["sample_id"])
            done += 1
        flash(f"{done} pixel-identieke waarden automatisch overgenomen.", "success")
        return redirect(url_for("review_home"))

    @app.get("/review/queue")
    def queue():
        filters = filter_args()
        try:
            page = max(int(request.args.get("page", "1")), 1)
        except ValueError:
            abort(400)
        samples = query_samples(filters, limit=60, offset=(page - 1) * 60)
        counts = value_review_counts()
        return render_template(
            "dashboard.html", fields=database.fields(), samples=samples,
            selected_status=filters["status"], selected_field=filters["field"],
            selected_min_confidence=filters["min_confidence"],
            selected_max_confidence=filters["max_confidence"],
            selected_ocr_content=filters["ocr_content"], page=page,
            header_counts=counts, header_total_label="waarden",
            header_pending_label="te beoordelen", header_accepted_label="goedgekeurd",
        )
