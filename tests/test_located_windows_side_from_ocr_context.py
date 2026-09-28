"""``_located_windows()`` (routes_documents.py) must still label a window
Links/Rechts when the configured Table/Panel Setup geometry does not cover
it -- for example because the report layout puts the tables somewhere else
on the page than the single reference layout that geometry was drawn
against (see the "V1/V2 always Onbekend" bug this covers). It reads
Identificatie's own already-OCR'd relations (generic_detections/<source_id>
.json), the same left/right vocabulary ``_relation_side``/``lateral.py``
already use elsewhere in the app, as its primary source of truth -- ahead of
the configured panel geometry, which only kicks in once OCR has nothing to
say for a window (Identificatie hasn't run yet, or no relation landed
inside it).
"""

from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.routes_documents import _located_windows
from isala_ocr.training.table_panels import save_panel_definitions, save_panel_profile


def _write_generic_detections(workspace: Path, source_id: str, *, blocks, relations) -> None:
    directory = workspace / "generic_detections"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{source_id}.json").write_text(
        json.dumps({"blocks": blocks, "relations": relations}), encoding="utf-8"
    )


def test_falls_back_to_ocr_context_when_no_panel_overlaps(tmp_path: Path) -> None:
    localization = {
        "source_id": "src1",
        "tables": [
            {"x1": 900, "y1": 20, "x2": 1570, "y2": 290},
            {"x1": 900, "y1": 460, "x2": 1570, "y2": 700},
        ],
    }
    _write_generic_detections(
        tmp_path,
        "src1",
        blocks=[
            {"block_id": "vb-top", "x1": 1000, "y1": 40, "x2": 1100, "y2": 60},
            {"block_id": "vb-bottom", "x1": 1000, "y1": 480, "x2": 1100, "y2": 500},
        ],
        relations=[
            {"value_block_id": "vb-top", "context_text": "Left ventricle Volume Result"},
            {"value_block_id": "vb-bottom", "context_text": "Right Ventricle Volume Result"},
        ],
    )

    windows = _located_windows(tmp_path, localization, image_width=1574, image_height=876)

    assert [w["table_label"] for w in windows] == ["Links", "Rechts"]


def test_stays_onbekend_without_any_ocr_context(tmp_path: Path) -> None:
    localization = {
        "source_id": "src1",
        "tables": [{"x1": 900, "y1": 20, "x2": 1570, "y2": 290}],
    }

    windows = _located_windows(tmp_path, localization, image_width=1574, image_height=876)

    assert windows[0]["table_label"] == "Onbekend"


def test_ocr_context_overrides_conflicting_panel_geometry(tmp_path: Path) -> None:
    save_panel_definitions(
        tmp_path,
        definitions=[{"panel_id": "left", "name": "Links"}, {"panel_id": "right", "name": "Rechts"}],
    )
    save_panel_profile(
        tmp_path,
        panels=[
            {"panel_id": "left", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 0.5},
            {"panel_id": "right", "x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 1.0},
        ],
    )
    localization = {
        "source_id": "src1",
        # Sits fully inside the configured "left" panel geometry above...
        "tables": [{"x1": 900, "y1": 20, "x2": 1570, "y2": 290}],
    }
    _write_generic_detections(
        tmp_path,
        "src1",
        blocks=[{"block_id": "vb", "x1": 1000, "y1": 40, "x2": 1100, "y2": 60}],
        relations=[{"value_block_id": "vb", "context_text": "Right Ventricle Volume Result"}],
    )

    windows = _located_windows(tmp_path, localization, image_width=1574, image_height=876)

    # ...but its own OCR'd content says Right, and OCR is the primary signal.
    assert windows[0]["table_label"] == "Rechts"


def test_majority_vote_ignores_a_single_stray_mismatched_relation(tmp_path: Path) -> None:
    localization = {
        "source_id": "src1",
        "tables": [{"x1": 900, "y1": 20, "x2": 1570, "y2": 290}],
    }
    _write_generic_detections(
        tmp_path,
        "src1",
        blocks=[
            {"block_id": "vb-a", "x1": 1000, "y1": 40, "x2": 1100, "y2": 60},
            {"block_id": "vb-b", "x1": 1000, "y1": 80, "x2": 1100, "y2": 100},
            {"block_id": "vb-c", "x1": 1000, "y1": 120, "x2": 1100, "y2": 140},
        ],
        relations=[
            {"value_block_id": "vb-a", "context_text": "Left ventricle Volume Result"},
            {"value_block_id": "vb-b", "context_text": "Left ventricle Ejection Fraction"},
            {"value_block_id": "vb-c", "context_text": "Rechts"},
        ],
    )

    windows = _located_windows(tmp_path, localization, image_width=1574, image_height=876)

    assert windows[0]["table_label"] == "Links"
