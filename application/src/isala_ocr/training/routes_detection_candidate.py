"""Detection-candidate crop image route, split out of webui.create_web_app.

Same pattern as routes_media.py: a small, read-only image-serving
endpoint. Its shared dependencies (the active project ``database``
proxy, ``safe_workspace_file`` and the request-scoped render-image
cache ``cached_render_image``, also used by the still-inline
``detected_block_crop`` route) stay in webui.py and are passed in
explicitly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, abort, send_file


def register_detection_candidate_routes(
    app: Flask,
    *,
    database: Any,
    safe_workspace_file: Callable[[str | Path], Path],
    cached_render_image: Callable[[Path], Any],
) -> None:
    @app.get("/detection-candidate/<source_id>/<candidate_id>.png")
    def detection_candidate_crop(source_id: str, candidate_id: str):
        candidate = database.get_detection_candidate(source_id, candidate_id)
        source = database.get_detection_source(source_id)
        if candidate is None or source is None:
            abort(404)
        relative = str(candidate.get("crop_path") or "")
        if relative:
            path = safe_workspace_file(relative)
            if path.is_file():
                return send_file(path, mimetype="image/png", max_age=0)
        render = safe_workspace_file(str(source.get("render_path") or ""))
        if not render.is_file():
            abort(404)
        import cv2

        image = cached_render_image(render)
        if image is None:
            abort(404)
        x1, y1, x2, y2 = (int(candidate[key]) for key in ("x1", "y1", "x2", "y2"))
        crop = image[y1:y2, x1:x2]
        if not crop.size:
            abort(404)
        ok, encoded = cv2.imencode(".png", crop)
        if not ok:
            abort(500)
        return Response(encoded.tobytes(), mimetype="image/png", headers={"Cache-Control": "no-store"})
