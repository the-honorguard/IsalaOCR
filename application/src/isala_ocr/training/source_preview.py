from __future__ import annotations

from pathlib import Path

import cv2

from ..config import AppConfig
from ..image_io import load_input
from .db import TrainingDatabase
from .input_selection import selected_input_files
from .projects import resolve_project_workspace


def prepare_source_renders(input_path: str | Path, workspace: str | Path, config: AppConfig) -> dict[str, object]:
    """Create full source renders for Panel Setup without OCR or inference."""
    root = resolve_project_workspace(workspace)
    render_root = root / "source_renders"
    render_root.mkdir(parents=True, exist_ok=True)
    database = TrainingDatabase(root / "samples.sqlite3")
    completed = 0
    for source in selected_input_files(Path(input_path), root):
        decoded = load_input(source, config.dicom)
        render_relative = Path("source_renders") / f"{decoded.source_id}.png"
        render_path = root / render_relative
        if not cv2.imwrite(str(render_path), decoded.image):
            raise RuntimeError(f"Could not save local source render: {render_path}")
        database.replace_localization_detection(
            {"source_id": decoded.source_id, "image_width": int(decoded.image.shape[1]),
             "image_height": int(decoded.image.shape[0]), "render_path": render_relative.as_posix(),
             "detector_version": "source-render-only", "token_count": 0},
            [], [],
        )
        completed += 1
    return {"sources": completed, "source_render_directory": "source_renders", "inference_performed": False}
