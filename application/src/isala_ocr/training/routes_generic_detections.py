"""Generic-detections routes, split out of webui.create_web_app.

Covers the ``/detections`` overview, the per-source ``/detections/<source_id>``
block browser and the ``/detected-block/<block_id>`` crop-serving endpoint.
``database``, ``safe_workspace_file``, ``cached_render_image`` and
``current_pipeline_gate`` are still shared with other route groups defined
directly in webui.py, so they are passed in explicitly rather than
re-implemented here — the same approach used by ``routes_home.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import cv2
from flask import Flask, Response, abort, render_template, request, send_file

from .mapping import resolve_value_roi_box


def register_generic_detections_routes(
    app: Flask,
    *,
    database: Any,
    safe_workspace_file: Callable[[str | Path], Path],
    cached_render_image: Callable[[Path], Any],
    current_pipeline_gate: Callable[[], dict[str, Any]],
) -> None:
    @app.get("/detections")
    def generic_detections():
        gate = current_pipeline_gate()
        if not gate.get("ready"):
            return render_template("mapping_blocked.html", gate=gate), 423
        mapping = database.mapping_counts()
        return render_template(
            "generic_detections.html",
            sources=database.list_detection_sources(),
            mapping=mapping,
            header_counts={"total": mapping.get("relations", 0), "pending": mapping.get("suggested", 0), "accepted": mapping.get("confirmed", 0)},
            header_total_label="relaties", header_pending_label="voorgesteld", header_accepted_label="bevestigd",
        )

    @app.get("/detections/<source_id>")
    def generic_detection_document(source_id: str):
        gate = current_pipeline_gate()
        if not gate.get("ready"):
            return render_template("mapping_blocked.html", gate=gate), 423
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        role = str(request.args.get("role", "candidates")).strip().lower()
        if role not in {"candidates", "semantic", "all", "table", "label", "value", "header", "unit", "unknown"}:
            abort(400)
        blocks = database.list_detected_blocks(
            source_id,
            role=None if role in {"candidates", "semantic", "all", "table"} else role,
            semantic_only=(role in {"candidates", "semantic"}),
        )
        if role == "candidates":
            blocks = [item for item in blocks if item.get("role") in {"label", "value"}]
        elif role == "table":
            blocks = [item for item in database.list_detected_blocks(source_id) if item.get("block_type") in {"table", "table_cell"}]
        relations = database.list_detected_relations(source_id)
        value_preview_needed = any(
            item.get("role") == "value" and item.get("block_type") in {"semantic", "table_cell"}
            for item in blocks
        )
        source_annotations = database.list_detection_annotations(source_id, active_only=True) if value_preview_needed else []
        source_candidates = database.list_detection_candidates(source_id) if value_preview_needed else []
        for block in blocks:
            block["crop_exists"] = bool(block.get("crop_path")) and safe_workspace_file(str(block.get("crop_path") or "")).is_file()
            block["display_x1"] = int(block["x1"]); block["display_y1"] = int(block["y1"])
            block["display_x2"] = int(block["x2"]); block["display_y2"] = int(block["y2"])
            block["geometry_source"] = "detected"
            if block.get("role") == "value" and block.get("block_type") in {"semantic", "table_cell"}:
                try:
                    preview_box, preview_diag = resolve_value_roi_box(
                        database, str(block["block_id"]), int(source["image_width"]), int(source["image_height"]),
                        block=block, annotations=source_annotations, candidates=source_candidates,
                    )
                    block["display_x1"], block["display_y1"], block["display_x2"], block["display_y2"] = preview_box.to_list()
                    block["geometry_source"] = str(preview_diag.get("geometry_source") or "refined")
                except (KeyError, ValueError):
                    pass
        mapping_counts = database.mapping_counts()
        return render_template(
            "generic_detection.html",
            source=source,
            source_id=source_id,
            blocks=blocks,
            relations=relations,
            role_filter=role,
            field_definitions=database.list_field_definitions(active_only=True),
            header_counts={"total": len(relations), "pending": max(0, len(relations) - mapping_counts.get("confirmed", 0)), "accepted": mapping_counts.get("confirmed", 0)},
            header_total_label="relaties", header_pending_label="open", header_accepted_label="bevestigd",
        )

    @app.get("/detected-block/<block_id>")
    def detected_block_crop(block_id: str):
        if not current_pipeline_gate().get("ready"):
            abort(423, description="Pipeline A geometry gate is gesloten")
        block = database.get_detected_block(block_id)
        if block is None:
            abort(404)
        mode = str(request.args.get("mode") or "detected").strip().lower()
        if mode == "roi" and str(block.get("role") or "") == "value":
            source = database.get_detection_source(str(block["source_id"]))
            if source is None:
                abort(404)
            render = safe_workspace_file(str(source.get("render_path") or ""))
            if not render.is_file():
                abort(404)
            image = cached_render_image(render)
            if image is None:
                abort(404)
            height, width = image.shape[:2]
            try:
                box, _ = resolve_value_roi_box(database, block_id, width, height)
            except (KeyError, ValueError):
                abort(404)
            crop = image[box.y1:box.y2, box.x1:box.x2]
            if crop.size == 0:
                abort(404)
            ok, encoded = cv2.imencode(".png", crop)
            if not ok:
                abort(500)
            return Response(encoded.tobytes(), mimetype="image/png", headers={"Cache-Control": "no-store"})
        if not str(block.get("crop_path") or ""):
            abort(404)
        path = safe_workspace_file(str(block["crop_path"]))
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)
