from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.localization_dataset import (
    _dataset_source_splits,
    _safe_auto_split_targets,
    build_localization_dataset,
    localization_dataset_preview,
    save_localization_split_config,
)

ROOT = Path(__file__).resolve().parents[1]


def _add_ready_source(workspace: Path, db: TrainingDatabase, source_id: str) -> None:
    render = workspace / "source_renders" / f"{source_id}.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(render), np.zeros((60, 120, 3), dtype=np.uint8))
    source = {
        "source_id": source_id,
        "image_width": 120,
        "image_height": 60,
        "render_path": render.relative_to(workspace).as_posix(),
        "detector_version": "test",
        "token_count": 0,
    }
    candidate = {
        "candidate_id": f"{source_id}-c1",
        "source_id": source_id,
        "confidence": 0.9,
        "source_kind": "text_geometry",
        "source_refs": [],
        "crop_path": "",
        "x1": 10,
        "y1": 10,
        "x2": 50,
        "y2": 28,
    }
    db.replace_localization_detection(source, [candidate], [])
    db.review_detection_candidate(source_id=source_id, candidate_id=f"{source_id}-c1", review_status="correct")
    db.set_detection_source_review_completed(source_id, True)


def test_safe_auto_split_is_9_2_3_for_fourteen_sources() -> None:
    assert _safe_auto_split_targets(14) == {"train": 9, "val": 2, "test": 3}


def test_preview_uses_exact_safe_counts_for_small_dataset(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for index in range(14):
        _add_ready_source(workspace, db, f"source-{index:02d}")
    preview = localization_dataset_preview(workspace)
    assert preview["totals"]["ready_sources"] == 14
    assert preview["splits"] == {"train": 9, "val": 2, "test": 3}
    assert preview["split_plan"]["auto_targets"] == {"train": 9, "val": 2, "test": 3}


def test_manual_source_override_preserves_counts_and_is_built_immutably(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for index in range(14):
        _add_ready_source(workspace, db, f"source-{index:02d}")
    before = localization_dataset_preview(workspace)
    train_source = next(row["source_id"] for row in before["sources"] if row["split"] == "train")

    plan = save_localization_split_config(
        workspace,
        mode="counts",
        targets={"train": 9, "val": 2, "test": 3},
        overrides={train_source: "test"},
    )
    assert plan["counts"] == {"train": 9, "val": 2, "test": 3}
    assert plan["assignments"][train_source] == "test"
    assert (workspace / "localization_split_pending.flag").is_file()

    preview = localization_dataset_preview(workspace)
    selected = next(row for row in preview["sources"] if row["source_id"] == train_source)
    assert selected["split"] == "test"
    assert selected["split_override"] == "test"

    manifest = build_localization_dataset(workspace)
    assert manifest["splits"]["train"]["images"] == 9
    assert manifest["splits"]["val"]["images"] == 2
    assert manifest["splits"]["test"]["images"] == 3
    assert manifest["source_splits"][train_source] == "test"
    assert manifest["split_policy"]["overrides"][train_source] == "test"
    assert not (workspace / "localization_split_pending.flag").exists()
    assert _dataset_source_splits(workspace, manifest["dataset_id"]) == manifest["source_splits"]


def test_step_four_exposes_counts_and_per_source_split_controls() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")
    assert "Verdeling sturen" in template
    assert 'name="split_train"' in template
    assert 'name="split_val"' in template
    assert 'name="split_test"' in template
    assert 'name="split_choice"' in template
    assert "Veilige auto herstellen" in template
    assert "Auto → {{ src.split }}" in template
    assert "volgende dataset-build" in template


def test_training_preflight_blocks_when_split_changed_after_build() -> None:
    script = (ROOT / "automation/powershell/preflight.ps1").read_text(encoding="utf-8")
    assert "localization_split_pending.flag" in script
    assert "$splitManifestReady" in script
    assert "source_splits" in script
    assert "split_current={4}" in script
    assert "geparkeerde fallbackpagina Losse box-detector trainen" in script
