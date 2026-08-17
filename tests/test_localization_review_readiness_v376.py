from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.localization_dataset import build_localization_dataset, localization_dataset_preview

ROOT = Path(__file__).resolve().parents[1]


def _source(workspace: Path, db: TrainingDatabase, source_id: str) -> dict:
    render = workspace / "source_renders" / f"{source_id}.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(render), np.zeros((100, 200, 3), dtype=np.uint8))
    source = {"source_id": source_id, "image_width": 200, "image_height": 100,
              "render_path": render.relative_to(workspace).as_posix(), "detector_version": "test", "token_count": 0}
    db.replace_localization_detection(source, [{"candidate_id": "c1", "source_id": source_id, "confidence": .9,
        "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 10, "y1": 10, "x2": 60, "y2": 30}], [])
    return source


def test_builder_requires_image_level_review_completion(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    _source(workspace, db, "s1")
    db.review_detection_candidate(source_id="s1", candidate_id="c1", review_status="correct")
    preview = localization_dataset_preview(workspace)
    assert preview["totals"]["ready_sources"] == 0
    assert preview["sources"][0]["included"] is False
    with pytest.raises(ValueError, match="review-completed"):
        build_localization_dataset(workspace)

    db.set_detection_source_review_completed("s1", True)
    preview = localization_dataset_preview(workspace)
    assert preview["totals"]["ready_sources"] == 1
    assert preview["sources"][0]["included"] is True
    assert build_localization_dataset(workspace)["image_count"] == 1


def test_finish_image_can_include_remaining_candidates_by_default(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    _source(workspace, db, "s1")
    assert db.detection_review_counts("s1")["pending"] == 1
    db.set_detection_source_review_completed("s1", True, accept_unreviewed=True)
    assert db.detection_review_counts("s1")["pending"] == 0
    assert db.detection_review_counts("s1")["positive"] == 1
    assert db.get_detection_source("s1")["review_completed"] == 1


def test_review_ui_is_exception_first_and_has_image_done_gate() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    index = (ROOT / "application/src/isala_ocr/training/templates/detection_review_index.html").read_text(encoding="utf-8")
    assert 'id="dock-include"' in template
    assert 'id="dock-irrelevant"' in template
    assert 'id="dock-reject"' in template
    assert 'id="dock-edit"' in template
    assert 'id="default-include" checked' in template
    assert 'id="source-done"' in template
    assert "Rest standaard includeren" in template
    assert "Afbeelding klaar" in template
    assert "/process/detection-status" not in index


def test_dataset_preview_ui_explains_exact_inclusion_gate() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")
    assert "Dit gaat daadwerkelijk de detector-training in" in template
    assert "✓ Afbeelding klaar" in template
    assert "wordt volledig uitgesloten" in template
    assert "Worden meegenomen" in template
    assert "Uitgesloten" in template
    assert "Positieve ROI's" in template
    assert "Niet relevant / incorrect" in template
    assert "dataset-preview-table" in template
    assert "src.included" in template
