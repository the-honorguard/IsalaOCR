"""``build_table_cell_dataset``/``table_cell_dataset_preview`` used to abort
entirely when even a single reviewed source's ``source_renders/<id>.png`` was
missing from disk (for example after a manual workspace cleanup), even though
every other reviewed source was perfectly usable. The render is a derived
artifact, not ground truth, so a missing one must be skipped -- loudly, via a
surfaced warning -- rather than blocking the whole Step 6 dataset build.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_panels import save_panel_profile
from isala_ocr.training.table_cell_training import build_table_cell_dataset, table_cell_dataset_preview


def _seed_review(workspace: Path, source_id: str, *, write_render: bool) -> None:
    renders = workspace / "source_renders"
    renders.mkdir(parents=True, exist_ok=True)
    if write_render:
        Image.new("RGB", (300, 200), "white").save(renders / f"{source_id}.png")
    db = TrainingDatabase(workspace / "samples.sqlite3")
    candidate_id = f"{source_id}-cell-1"
    candidates = [
        {"candidate_id": candidate_id, "source_id": source_id, "confidence": 0.95, "source_kind": "table_cell",
         "source_refs": ["table:t:cell:1"], "crop_path": "", "x1": 20, "y1": 20, "x2": 140, "y2": 48},
    ]
    db.replace_localization_detection(
        {"source_id": source_id, "image_width": 300, "image_height": 200,
         "render_path": f"source_renders/{source_id}.png", "detector_version": "ppstructure", "token_count": 0},
        candidates, [],
    )
    db.review_detection_candidate(source_id=source_id, candidate_id=candidate_id, review_status="correct")
    db.set_detection_source_review_completed(source_id, True)


def test_preview_skips_a_source_whose_render_is_missing_and_reports_a_warning(tmp_path: Path) -> None:
    save_panel_profile(
        tmp_path, panels=[{"panel_id": "lv", "name": "LV", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id="source-ok", reference_width=300, reference_height=200,
    )
    _seed_review(tmp_path, "source-ok", write_render=True)
    _seed_review(tmp_path, "source-missing-render", write_render=False)

    preview = table_cell_dataset_preview(tmp_path)

    assert preview["source_count"] == 1, "the source without a render must not be counted"
    assert preview["ready"] is True, "the remaining, usable source must still make the dataset buildable"
    assert any("source-missing-render" in warning for warning in preview["warnings"])


def test_build_skips_a_source_whose_render_is_missing_and_still_builds_the_rest(tmp_path: Path) -> None:
    save_panel_profile(
        tmp_path, panels=[{"panel_id": "lv", "name": "LV", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id="source-ok", reference_width=300, reference_height=200,
    )
    _seed_review(tmp_path, "source-ok", write_render=True)
    _seed_review(tmp_path, "source-missing-render", write_render=False)

    manifest = build_table_cell_dataset(tmp_path)

    assert manifest["source_count"] == 1
    assert any("source-missing-render" in warning for warning in manifest["dataset_warnings"])
    panel_sources = {panel["source_id"] for panel in manifest["panels"]}
    assert panel_sources == {"source-ok"}
