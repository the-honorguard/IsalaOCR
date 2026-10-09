from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.models import Box
from isala_ocr.training.collector import _apply_panel_identity_from_located_regions
from isala_ocr.training.generic_detection import GenericBlock, GenericRelation
from isala_ocr.training.table_panels import save_panel_definitions, save_panel_profile


def _block(block_id: str, text: str, box: Box, *, kind: str = "semantic", role: str = "header") -> GenericBlock:
    return GenericBlock(block_id, "source", kind, role, text, text.casefold(), 0.95, box, 0, 0)


def test_outside_side_headings_identify_each_table_despite_stale_panel_boxes(tmp_path: Path) -> None:
    save_panel_definitions(tmp_path, definitions=[
        {"panel_id": "left", "name": "Links", "hits": ["left"]},
        {"panel_id": "right", "name": "Rechts", "hits": ["right"]},
    ])
    save_panel_profile(tmp_path, panels=[
        {"panel_id": "left", "x1": 0.0, "y1": 0.04, "x2": 0.32, "y2": 0.32},
        {"panel_id": "right", "x1": 0.0, "y1": 0.59, "x2": 0.32, "y2": 0.87},
    ])
    localization = tmp_path / "localization_detections"
    localization.mkdir()
    (localization / "source.json").write_text(json.dumps({"tables": [
        {"x1": 5, "y1": 662, "x2": 640, "y2": 1183},
        {"x1": 658, "y1": 611, "x2": 1299, "y2": 1171},
    ]}), encoding="utf-8")
    blocks = [
        _block("joined", "Left ventricle Volume Result Right ventricle Volume Result", Box(163, 611, 1014, 628), kind="line", role="line"),
        _block("left-heading", "Left ventricle Volume Result", Box(233, 644, 423, 658)),
        _block("right-heading", "Right ventricle Volume Result", Box(813, 611, 1014, 628)),
        _block("left-value", "51 %", Box(160, 700, 210, 720), kind="table_cell", role="value"),
        _block("right-value", "50 %", Box(810, 700, 860, 720), kind="table_cell", role="value"),
    ]
    relations = [
        GenericRelation("left-rel", "source", None, "left-value", None, "table_cell", 0.9, 1, "Endo Volume Normal Values Chuang"),
        GenericRelation("right-rel", "source", None, "right-value", None, "table_cell", 0.9, 1, "Endo Volume Normal Values Chuang"),
    ]

    enriched = _apply_panel_identity_from_located_regions(tmp_path, "source", 1311, 1824, blocks, relations)

    assert [relation.context_text for relation in enriched] == ["Links", "Rechts"]


def test_custom_panel_keywords_map_only_the_recognized_table(tmp_path: Path) -> None:
    save_panel_definitions(tmp_path, definitions=[
        {"panel_id": "aorta", "name": "Aorta", "hits": ["Aortic flow"]},
        {"panel_id": "pulmonary", "name": "Pulmonary", "hits": ["Pulmonary flow"]},
    ])
    save_panel_profile(tmp_path, panels=[
        {"panel_id": "aorta", "x1": 0.0, "y1": 0.04, "x2": 0.32, "y2": 0.32},
        {"panel_id": "pulmonary", "x1": 0.0, "y1": 0.59, "x2": 0.32, "y2": 0.87},
    ])
    localization = tmp_path / "localization_detections"
    localization.mkdir()
    (localization / "source.json").write_text(json.dumps({"tables": [
        {"x1": 40, "y1": 220, "x2": 360, "y2": 470},
        {"x1": 420, "y1": 220, "x2": 760, "y2": 470},
    ]}), encoding="utf-8")
    blocks = [
        _block("joined", "Aortic flow Pulmonary flow", Box(100, 190, 700, 210), kind="line", role="line"),
        _block("aorta-heading", "Aortic flow", Box(100, 190, 250, 210)),
        _block("aorta-value", "4.2", Box(140, 250, 190, 270), kind="table_cell", role="value"),
        _block("pulmonary-value", "3.9", Box(560, 250, 610, 270), kind="table_cell", role="value"),
    ]
    relations = [
        GenericRelation("aorta-rel", "source", None, "aorta-value", None, "table_cell", 0.9, 1, "Flow Results"),
        GenericRelation("pulmonary-rel", "source", None, "pulmonary-value", None, "table_cell", 0.9, 1, "Flow Results"),
    ]

    enriched = _apply_panel_identity_from_located_regions(tmp_path, "source", 800, 600, blocks, relations)

    assert [relation.context_text for relation in enriched] == ["Aorta", "Flow Results"]
