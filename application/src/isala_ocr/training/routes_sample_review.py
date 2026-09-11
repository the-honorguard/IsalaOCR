"""Single-sample value-review routes, split out of webui.create_web_app.

Same pattern as the other ``routes_*`` modules split out of ``webui.py``:
the handlers move here, but the helpers they depend on (``_filter_args``,
``query_samples`` and ``value_review_counts`` - all also used by the
still-inline ``/review/queue`` route, plus the active project
``database`` proxy) stay in webui.py and are passed in explicitly
(``_filter_args`` is a module-level function there, but importing it
back from here would create a webui.py <-> routes_sample_review
circular import, since webui.py imports this module to register its
routes).
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, abort, redirect, render_template, request, url_for


def register_sample_review_routes(
    app: Flask,
    *,
    database: Any,
    filter_args: Callable[[], dict[str, str | None]],
    query_samples: Callable[..., list[dict[str, Any]]],
    value_review_counts: Callable[[], dict[str, int]],
) -> None:
    @app.get("/sample/<sample_id>")
    def sample(sample_id: str):
        current = database.get(sample_id)
        if not current or current["roi_review_status"] != "correct":
            abort(404)
        filters = filter_args()
        candidates = query_samples(filters, limit=10000)
        ids = [item["sample_id"] for item in candidates]
        try:
            index = ids.index(sample_id)
        except ValueError:
            index = -1
        counts = value_review_counts()
        return render_template(
            "sample.html", sample=current,
            previous_id=ids[index - 1] if index > 0 else None,
            next_id=ids[index + 1] if 0 <= index < len(ids) - 1 else None,
            filters=filters, header_counts=counts, header_total_label="waarden",
            header_pending_label="te beoordelen", header_accepted_label="goedgekeurd",
        )

    @app.post("/sample/<sample_id>")
    def sample_review(sample_id: str):
        current = database.get(sample_id)
        if not current or current["roi_review_status"] != "correct":
            abort(404)
        action = request.form.get("action", "value_save")
        notes = request.form.get("notes", "")
        label = request.form.get("exact_label", "")
        if action in {"value_correct", "ocr_correct"}:
            database.review(sample_id, "accepted", current["raw_ocr"], notes, "value")
        elif action in {"value_save", "save"}:
            database.review(sample_id, "accepted", label, notes, "value")
        elif action == "placeholder":
            database.review(sample_id, "accepted", label, notes, "placeholder")
        elif action == "no_value":
            database.review(sample_id, "no_value", None, notes, "no_value")
        elif action in {"unreadable", "excluded", "pending"}:
            database.review(sample_id, action, None, notes)
        else:
            abort(400)
        return redirect(url_for("queue"))
