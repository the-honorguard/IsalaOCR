"""Table-panel review-source JSON API, split out of webui.create_web_app.

The heavy lifting (``_table_panel_review_context``) stays in webui.py
because it is also called directly from the ``/process/<step_key>``
mega-route; only this thin JSON wrapper moves out, taking the context
builder as an explicit dependency.
"""

from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify


def register_table_panel_review_routes(
    app: Flask,
    *,
    table_panel_review_context: Callable[[str], dict[str, Any]],
) -> None:
    @app.get("/api/table-panel-review-source/<source_id>")
    def table_panel_review_source_api(source_id: str):
        context = table_panel_review_context(source_id)
        source = context["source"]
        if source is None or context["source_id"] != source_id:
            return jsonify({"error": "Bron niet gevonden"}), 404
        return jsonify({
            "source": {
                "source_id": context["source_id"],
                "image_width": int(source.get("image_width") or 0),
                "image_height": int(source.get("image_height") or 0),
                "image_url": f"/source-render/{context['source_id']}.png",
            },
            "region_ground_truth": context["region_ground_truth"],
            "suggestions": context["suggestions"],
            "review_sources": context["table_review_sources"],
            "detection_info": context["detection_info"],
        })
