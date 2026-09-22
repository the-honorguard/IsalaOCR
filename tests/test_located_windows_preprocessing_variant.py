"""``_located_windows()`` (routes_documents.py) surfaces which preprocessing
variant (original/grayscale/clahe/invert_clahe/adaptive -- see
``detect_with_benchmark()`` in table_structure.py) actually won for each
table window, and its score. The proefpagina compare screen shows this so a
"why do two runs of the same model on the same pixels disagree" question can
be answered from the page itself: a low-contrast table can score very
differently between runs on the weaker variants while the winning
(usually contrast-boosted) variant stays stable, so the winning variant is
what actually explains a stable-looking final result despite noisy
underlying benchmarking.
"""

from __future__ import annotations

from pathlib import Path

from isala_ocr.training.routes_documents import _located_windows


def test_windows_matched_to_benchmark_regions_by_top_to_bottom_order(tmp_path: Path) -> None:
    localization = {
        "tables": [
            {"x1": 2, "y1": 480, "x2": 560, "y2": 800},
            {"x1": 4, "y1": 30, "x2": 560, "y2": 380},
        ],
        "preprocessing_benchmark": {
            "regions": [
                {"region_index": 1, "region_box": [3, 32, 568, 380], "selected_variant": "invert_clahe", "selected_score": 95.12},
                {"region_index": 2, "region_box": [2, 481, 561, 805], "selected_variant": "original", "selected_score": 94.96},
            ],
        },
    }
    windows = _located_windows(tmp_path, localization, image_width=1636, image_height=836)

    assert [w["window_index"] for w in windows] == [1, 2]
    top_window, bottom_window = windows
    assert top_window["preprocessing_variant"] == "invert_clahe"
    assert top_window["preprocessing_score"] == 95.12
    assert bottom_window["preprocessing_variant"] == "original"
    assert bottom_window["preprocessing_score"] == 94.96


def test_missing_benchmark_data_leaves_variant_and_score_unset(tmp_path: Path) -> None:
    localization = {"tables": [{"x1": 4, "y1": 30, "x2": 560, "y2": 380}]}
    windows = _located_windows(tmp_path, localization, image_width=1636, image_height=836)

    assert len(windows) == 1
    assert windows[0]["preprocessing_variant"] is None
    assert windows[0]["preprocessing_score"] is None
