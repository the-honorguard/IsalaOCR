from __future__ import annotations

import numpy as np

from isala_ocr.models import Box
from isala_ocr.ocr.table_structure import (
    TableCell,
    TableRegion,
    _panel_crop_from_regions,
    _preprocess_table_image,
    score_table_structure,
)


def _region(*, noisy: bool = False) -> TableRegion:
    cells = []
    for row in range(6):
        for col in range(3):
            x1 = 20 + col * 100 + (20 if noisy and row % 2 else 0)
            y1 = 20 + row * 28
            box = Box(x1, y1, x1 + 86, y1 + 22)
            cells.append(TableCell("t", f"c-{row}-{col}", row, col, box, "", 0.9))
    if noisy:
        cells.append(TableCell("t", "overlap", 0, 1, Box(105, 20, 205, 42), "", 0.9))
    return TableRegion("t", Box(15, 15, 330, 200), 0.9, tuple(cells))


def test_preprocessing_variants_keep_geometry_dimensions():
    image = np.zeros((120, 240, 3), dtype=np.uint8)
    image[:, 100:140] = 180
    for variant in ("original", "grayscale", "clahe", "invert_clahe", "adaptive"):
        out = _preprocess_table_image(image, variant)
        assert out.shape == image.shape
        assert out.dtype == np.uint8


def test_regular_table_scores_better_than_misaligned_overlapping_table():
    regular = score_table_structure([_region(noisy=False)])
    noisy = score_table_structure([_region(noisy=True)])
    assert regular["score"] > noisy["score"]
    assert regular["column_alignment"] > noisy["column_alignment"]


def test_panel_crop_is_padded_and_rejects_fullscreen_false_table():
    crop = _panel_crop_from_regions([_region()], 1000, 700)
    assert crop is not None
    assert crop.x1 < 15 and crop.y1 < 15
    full = TableRegion("full", Box(0, 0, 1000, 700), 0.9, _region().cells)
    assert _panel_crop_from_regions([full], 1000, 700) is None


def test_review_studio_exposes_smart_fit_and_reconstruction_controls():
    # The old smart-fit/normalize-column buttons were replaced by a raster
    # tool (draw an outer box, then configure rows/columns to slice it into
    # a grid of cells) - see draw-grid/raster-config/snap-row-bounds below.
    # The reconstructed-cell-suggestion overlay is still current.
    source = open("application/src/isala_ocr/training/templates/detection_review_studio.html", encoding="utf-8").read()
    assert 'id="draw-grid"' in source
    assert 'id="raster-config"' in source
    assert 'id="snap-row-bounds"' in source
    assert "reconstructed-cell-suggestion" in source
    assert "Geometrisch gereconstrueerd" in source



def test_reconstruction_suggestion_pointer_is_not_captured_by_marquee():
    source = open("application/src/isala_ocr/training/templates/detection_review_studio.html", encoding="utf-8").read()
    assert "e.target.closest('.reconstructed-cell-suggestion')" in source
    assert "button.addEventListener('pointerdown',e=>e.stopPropagation())" in source
    assert "Toevoegen reconstructie mislukt:" in source


def test_table_first_config_enables_preprocessing_benchmark():
    config = open("application/config/app.yaml", encoding="utf-8").read()
    assert "preprocessing_benchmark: true" in config
    assert "panel_mode: manual" in config
    assert "auto_panel_crop: false" in config
    assert "invert_clahe" in config


def test_table_quality_counts_geometric_reconstruction_separately(tmp_path):
    from isala_ocr.training.db import TrainingDatabase
    from isala_ocr.training.table_quality import table_first_quality

    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    candidate = {
        "candidate_id": "cell-0", "source_id": "source-a", "confidence": 0.9,
        "source_kind": "table_cell", "source_refs": ["table:t:cell:0"], "crop_path": "",
        "x1": 10, "y1": 10, "x2": 100, "y2": 30,
    }
    db.replace_localization_detection(
        {"source_id": "source-a", "image_width": 300, "image_height": 200,
         "render_path": "source_renders/source-a.png", "detector_version": "table", "token_count": 0},
        [candidate], [],
    )
    db.review_detection_candidate(source_id="source-a", candidate_id="cell-0", review_status="correct")
    reconstructed = db.add_detection_annotation(
        source_id="source-a", box=(110, 10, 200, 30), reason_code="table_geometry_error",
        notes="Geometrisch gereconstrueerd uit table t, rij 1, kolom 2",
    )
    assert reconstructed["provenance"] == "added"
    assert reconstructed["training_role"] == "positive"
    db.add_detection_annotation(source_id="source-a", box=(210, 10, 290, 30), notes="Echt handmatig")
    db.set_detection_source_review_completed("source-a", True)

    totals = table_first_quality(db)["totals"]
    assert totals["reconstructed"] == 1
    assert totals["manual_added"] == 1
    assert totals["added"] == 2
    assert round(totals["direct_coverage"], 3) == 0.333
    assert round(totals["structural_coverage"], 3) == 0.667
    assert round(totals["fallback_need"], 3) == 0.333
