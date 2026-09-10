"""Read-only media/file-serving routes, split out of webui.create_web_app.

Same pattern as routes_status.register_status_routes and
routes_projects.register_project_routes: the handlers move here, but the
shared per-project state they need (``safe_workspace_file``, the active
project ``database`` proxy, the loaded app config) stays defined in
webui.py because many other route groups there also depend on it, and is
passed in explicitly instead of re-implemented.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, send_file

from ..config import AppConfig
from ..image_io import load_input

_DATASET_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_RELATIVE_PATH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}")


def register_media_routes(
    app: Flask,
    *,
    database: Any,
    safe_workspace_file: Callable[[str | Path], Path],
    loaded_config: AppConfig | None,
) -> None:
    """Register the plain image/JSON file-serving endpoints.

    These only ever read a file under the active project's workspace (or,
    for ``input_preview``, the fixed ``/input`` mount) and stream it back;
    none of them touch the job queue, caches, or locks, so they need
    nothing beyond the workspace-file guard and the active database.
    """

    @app.get("/source-render/<source_id>.png")
    def source_render(source_id: str):
        path = safe_workspace_file(Path("source_renders") / f"{source_id}.png")
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    @app.get("/table-cell-dataset-image/<dataset_id>/<path:relative_path>")
    def table_cell_dataset_image(dataset_id: str, relative_path: str):
        if not _DATASET_ID_RE.fullmatch(dataset_id):
            abort(404)
        if Path(relative_path).name != relative_path or not _RELATIVE_PATH_RE.fullmatch(relative_path):
            abort(404)
        path = safe_workspace_file(Path("table_cell_datasets") / dataset_id / "images" / relative_path)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    @app.get("/input-preview/<path:relative_path>")
    def input_preview(relative_path: str):
        """Serve a safe visual preview for the pre-scan input selection screen."""
        root = Path("/input").resolve()
        path = (root / relative_path).resolve()
        suffix = path.suffix.lower()
        if root not in path.parents or not path.is_file():
            abort(404)
        if suffix in {".dcm", ".dicom"}:
            try:
                settings = loaded_config.dicom if loaded_config is not None else {}
                decoded = load_input(path, settings)
                import cv2

                ok, encoded = cv2.imencode(".jpg", decoded.image, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
                if not ok:
                    abort(404)
                return send_file(io.BytesIO(encoded.tobytes()), mimetype="image/jpeg", max_age=0)
            except Exception:
                abort(404)
        if suffix not in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
            abort(404)
        return send_file(path, max_age=0)

    @app.get("/dataset-image/<dataset_id>/<path:relative_path>")
    def dataset_image(dataset_id: str, relative_path: str):
        if not _DATASET_ID_RE.fullmatch(dataset_id):
            abort(404)
        path = safe_workspace_file(Path("datasets") / dataset_id / relative_path)
        if not path.is_file():
            abort(404)
        return send_file(path, max_age=0)

    @app.get("/extracted-output/<source_id>.json")
    def extracted_output(source_id: str):
        path = safe_workspace_file(Path("extracted_output") / f"{source_id}.json")
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="application/json", max_age=0)

    @app.get("/locator-overlay/<source_id>.png")
    def locator_overlay(source_id: str):
        path = safe_workspace_file(Path("locator_overlays") / f"{source_id}.png")
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    @app.get("/crop/<sample_id>")
    def crop(sample_id: str):
        sample = database.get(sample_id)
        if not sample:
            abort(404)
        path = safe_workspace_file(sample["crop_path"])
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)

    @app.get("/header-crop/<sample_id>")
    def header_crop(sample_id: str):
        sample = database.get(sample_id)
        if not sample:
            abort(404)
        relative = str(sample.get("header_crop_path") or "")
        if not relative:
            abort(404)
        path = safe_workspace_file(relative)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)
