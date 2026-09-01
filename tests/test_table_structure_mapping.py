from __future__ import annotations

from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.table_structure import parse_ppstructure_tables
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.generic_detection import detect_generic_structure, integrate_table_regions
from isala_ocr.training.mapping import build_mapping_output_preview, resolve_value_roi_box


def test_ppstructure_cells_create_ranked_table_relations() -> None:
    data = {
        "table_res_list": [
            {
                "cell_box_list": [
                    [10, 10, 120, 35], [130, 10, 220, 35], [230, 10, 360, 35],
                    [10, 40, 120, 65], [130, 40, 220, 65], [230, 40, 360, 65],
                    [10, 70, 120, 95], [130, 70, 220, 95], [230, 70, 360, 95],
                ],
                "structure_score": 0.98,
            }
        ]
    }
    tokens = [
        OCRToken("Measurement", 0.99, Box(15, 15, 105, 30)),
        OCRToken("Value", 0.99, Box(145, 15, 200, 30)),
        OCRToken("Normal", 0.99, Box(250, 15, 320, 30)),
        OCRToken("ED Volume", 0.99, Box(15, 45, 105, 60)),
        OCRToken("106.8 ml", 0.99, Box(145, 45, 205, 60)),
        OCRToken("88...227 ml", 0.97, Box(245, 45, 335, 60)),
        OCRToken("ES Volume", 0.99, Box(15, 75, 105, 90)),
        OCRToken("54.4 ml", 0.99, Box(145, 75, 200, 90)),
        OCRToken("23...105 ml", 0.97, Box(245, 75, 335, 90)),
    ]
    tables = parse_ppstructure_tables(
        data, source_id="source", fallback_tokens=tokens, image_width=400, image_height=120
    )
    assert len(tables) == 1
    assert len(tables[0].cells) == 9

    generic_blocks, generic_relations, _ = detect_generic_structure("source", (120, 400, 3), tokens)
    blocks, relations, diagnostics = integrate_table_regions(
        "source", generic_blocks, generic_relations, tables
    )
    by_id = {block.block_id: block for block in blocks}
    table_relations = [item for item in relations if item.relation_type == "table_cell"]
    assert diagnostics["table_count"] == 1
    assert len(table_relations) == 4
    ed = [item for item in table_relations if by_id[item.label_block_id].text == "ED Volume"]
    assert [item.rank for item in ed] == [1, 2]
    assert by_id[ed[0].value_block_id].text == "106.8 ml"
    assert by_id[ed[1].value_block_id].text == "88...227 ml"
    assert ed[0].row_index == 1
    assert ed[0].value_column_index == 1


def test_ppstructure_assigns_one_global_column_grid_across_rows() -> None:
    data = {
        "table_res_list": [{
            "cell_box_list": [
                [10, 10, 110, 35], [120, 10, 220, 35], [230, 10, 330, 35],
                [10, 40, 110, 65], [230, 40, 330, 65],
                [10, 70, 220, 95], [230, 70, 330, 95],
            ]
        }]
    }
    tables = parse_ppstructure_tables(data, source_id="source")
    cells = tables[0].cells

    assert [(cell.row_index, cell.column_index, cell.column_span) for cell in cells] == [
        (0, 0, 1), (0, 1, 1), (0, 2, 1),
        (1, 0, 1), (1, 2, 1),
        (2, 0, 2), (2, 2, 1),
    ]


def test_table_semantics_snap_to_reviewed_pipeline_a_geometry(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    blocks = [
        {
            "block_id": "token-value", "source_id": "s", "block_type": "token", "role": "value",
            "text": "106.8 ml", "normalized_text": "106 8 ml", "confidence": 0.99,
            "x1": 145, "y1": 45, "x2": 205, "y2": 60, "line_index": 1, "sequence_index": 1,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
        {
            "block_id": "cell-value", "source_id": "s", "block_type": "table_cell", "role": "value",
            "text": "106.8 ml", "normalized_text": "106 8 ml", "confidence": 0.98,
            "x1": 130, "y1": 40, "x2": 220, "y2": 65, "line_index": 1, "sequence_index": 1,
            "parent_block_id": "table", "context_text": "", "crop_path": "", "table_id": "t",
            "row_index": 1, "column_index": 1, "geometry_source": "ppstructurev3_cell",
        },
    ]
    source = {"source_id": "s", "image_width": 400, "image_height": 120, "render_path": "x.png", "detector_version": "test", "token_count": 1}
    db.replace_generic_detection(source, blocks, [])
    db.replace_localization_detection(
        source,
        [{"candidate_id": "value-roi", "source_id": "s", "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 143, "y1": 43, "x2": 207, "y2": 62}],
        [],
    )
    db.review_detection_candidate(
        source_id="s", candidate_id="value-roi", review_status="correct"
    )
    box, diagnostics = resolve_value_roi_box(db, "cell-value", 400, 120)
    assert diagnostics["geometry_source"] == "pipeline_a_reviewed_annotation"
    assert box == Box(143, 43, 207, 62)

def test_mapping_preview_matches_expected_output_shape() -> None:
    preview = build_mapping_output_preview(
        {
            "value_text": "106.8 ml", "label_text": "ED Volume", "confidence": 0.97,
            "relation_type": "table_cell", "table_id": "table-a", "row_index": 3,
            "value_column_index": 1,
        },
        {
            "field_key": "cardiac.rv.ed_volume", "display_name": "RV ED Volume",
            "group_name": "Right ventricle", "data_type": "decimal", "preferred_unit": "ml",
            "minimum_value": 20, "maximum_value": 400,
        },
    )
    item = preview["measurements"]["cardiac.rv.ed_volume"]
    assert item["raw_text"] == "106.8 ml"
    assert item["parsed_value"] == 106.8
    assert item["parsed_unit"] == "ml"
    assert item["range_valid"] is True
    assert item["source"]["relation_type"] == "table_cell"
    assert item["source"]["row_index"] == 3


def test_ppstructure_wrapper_keeps_cell_switches_at_predict_time(monkeypatch) -> None:
    import sys
    import types
    import numpy as np
    from isala_ocr.ocr import table_structure as module

    constructor_kwargs = {}
    predict_kwargs = {}

    class FakeResult:
        json = {"res": {"table_res_list": []}}

    class FakePipeline:
        def __init__(self, **kwargs):
            constructor_kwargs.update(kwargs)

        def predict(self, image, **kwargs):
            predict_kwargs.update(kwargs)
            return [FakeResult()]

    fake_paddleocr = types.SimpleNamespace(__version__="test", PPStructureV3=FakePipeline)
    monkeypatch.setitem(sys.modules, "paddleocr", fake_paddleocr)
    monkeypatch.setattr(module, "prepare_paddlex_runtime", lambda settings: None)

    engine = module.PPStructureTableEngine({"device": "cpu", "inference_engine": "paddle_static"}, {"enabled": True})
    assert engine.detect(np.zeros((100, 200, 3), dtype=np.uint8), source_id="s") == []
    assert "use_e2e_wireless_table_rec_model" not in constructor_kwargs
    assert constructor_kwargs["use_table_recognition"] is True
    assert predict_kwargs["use_e2e_wireless_table_rec_model"] is False
    assert predict_kwargs["use_e2e_wired_table_rec_model"] is False
    assert predict_kwargs["use_ocr_results_with_table_cells"] is False
