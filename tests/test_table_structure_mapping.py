from __future__ import annotations

from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.table_structure import (
    TableCell, normalize_table_column_layout, parse_ppstructure_tables, rasterize_table_columns,
)
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


def test_ppstructure_drops_full_width_studio_footer_after_regular_table() -> None:
    data = {
        "table_res_list": [{
            "cell_box_list": [
                [10, 10, 110, 35], [120, 10, 220, 35], [230, 10, 330, 35],
                [10, 40, 110, 65], [120, 40, 220, 65], [230, 40, 330, 65],
                [10, 70, 110, 95], [120, 70, 220, 95], [230, 70, 330, 95],
                [10, 106, 330, 121],
            ]
        }]
    }
    tables = parse_ppstructure_tables(data, source_id="source", image_width=400, image_height=140)
    assert len(tables) == 1
    assert len(tables[0].cells) == 9
    assert tables[0].box.y2 == 95


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


def test_isolated_header_is_outside_three_data_columns() -> None:
    """A top sub-header inside the value area must not create column four."""
    boxes = [[195, 10, 359, 28]]
    for row in range(3):
        y1 = 35 + row * 25
        boxes.extend([
            [5, y1, 151, y1 + 22],
            [147, y1, 367, y1 + 22],
            [367, y1, 530, y1 + 22],
        ])
    tables = parse_ppstructure_tables({"table_res_list": [{"cell_box_list": boxes}]}, source_id="header")
    cells = tables[0].cells
    assert [(cell.row_index, cell.column_index) for cell in cells] == [
        (0, -1), (1, 0), (1, 1), (1, 2),
        (2, 0), (2, 1), (2, 2), (3, 0), (3, 1), (3, 2),
    ]
    assert rasterize_table_columns(cells)[0].box == Box(195, 10, 359, 28)

    # Existing localization files have the old 0,1,2,3 numbering. Reading
    # them must produce the same layout without rewriting their raw boxes.
    old_indices = [2, *([0, 1, 3] * 3)]
    saved = [
        TableCell("t", str(index), cell.row_index, old_indices[index], cell.box, "", 0.9)
        for index, cell in enumerate(cells)
    ]
    repaired = normalize_table_column_layout(saved)
    assert [(cell.row_index, cell.column_index) for cell in repaired] == [
        (cell.row_index, cell.column_index) for cell in cells
    ]
    assert [cell.box for cell in repaired] == [cell.box for cell in saved]


def test_full_width_title_stays_outside_data_columns() -> None:
    boxes = [[5, 5, 549, 25]]
    for row in range(2):
        y1 = 35 + row * 25
        boxes.extend([
            [5, y1, 150, y1 + 22],
            [150, y1, 367, y1 + 22],
            [367, y1, 530, y1 + 22],
        ])
    cells = parse_ppstructure_tables(
        {"table_res_list": [{"cell_box_list": boxes}]}, source_id="title",
    )[0].cells
    assert cells[0].column_index == -1
    assert {cell.column_index for cell in cells[1:]} == {0, 1, 2}
    assert rasterize_table_columns(cells)[0].box == Box(5, 5, 549, 25)


def test_global_column_layout_merges_a_left_edge_split_value_column() -> None:
    """A value column split across two left-edge clusters, but sharing one
    right edge, must merge into a single column instead of staying split.

    Real production data (proefpagina source ``3cd1d917a4074a172c3946b3``):
    7 of 10 rows' value cell landed on a left edge around x=166-171, but 3
    rows (the one right after a sub-header, and two rows with an unusually
    short or missing value) landed on a left edge around x=221-223 instead
    -- a ~50px gap, just outside the left-edge clustering tolerance, so they
    formed a second, separate column. Both clusters' right edges, however,
    landed within a couple of pixels of each other either way. Without
    merging on that right-edge agreement, the 3 minority rows' relations
    never matched the mapping feedback trained on the majority pattern and
    were silently dropped from the datablok, even though their text was
    read correctly.
    """
    boxes = []
    # Minority cluster: 3 rows whose value cell starts further right (~221).
    for y1 in (10, 40, 310):
        boxes.append([5, y1, 165, y1 + 22])
        boxes.append([221, y1, 443, y1 + 22])
        boxes.append([443, y1, 660, y1 + 22])
    # Majority cluster: 7 rows whose value cell starts further left (~169),
    # ending at essentially the same right edge as the minority cluster.
    for y1 in (70, 100, 130, 160, 190, 220, 250):
        boxes.append([5, y1, 165, y1 + 22])
        boxes.append([169, y1, 442, y1 + 22])
        boxes.append([443, y1, 660, y1 + 22])
    cells = parse_ppstructure_tables({"table_res_list": [{"cell_box_list": boxes}]}, source_id="source")[0].cells

    value_cells = [cell for cell in cells if cell.box.x1 not in (5,) and cell.box.x2 not in (660,)]
    assert len(value_cells) == 10, "all 10 rows' value cells must survive -- none dropped as noise"
    assert {cell.column_index for cell in value_cells} == {1}, (
        "both left-edge clusters must land in the same shared column"
    )
    assert {cell.column_index for cell in cells} == {0, 1, 2}, "no fourth, orphaned column should remain"


def test_ppstructure_leaves_raw_per_row_cell_boxes_undisturbed() -> None:
    """Celdetectie (Pipeline A's persisted geometry) must stay the loose,
    un-rasterized boxes exactly as detected -- rasterization is an explicit,
    separate step (``rasterize_table_columns``), not something
    ``parse_ppstructure_tables`` does automatically, so the proefpagina's
    "Celdetectie" and "Rasterisering" stages can show genuinely different
    geometry.
    """
    data = {
        "table_res_list": [{
            "cell_box_list": [
                [10, 10, 110, 35], [120, 10, 220, 35],
                [8, 40, 105, 65], [122, 40, 218, 65],
            ]
        }]
    }
    tables = parse_ppstructure_tables(data, source_id="source")
    boxes = {(cell.column_index, cell.box.x1, cell.box.x2) for cell in tables[0].cells}
    assert boxes == {(0, 10, 110), (1, 120, 220), (0, 8, 105), (1, 122, 218)}


def test_rasterize_table_columns_widens_to_the_widest_detected_variant() -> None:
    """Row-to-row detection jitter within one column must not survive into the raster.

    Column 0's boxes are a few pixels narrower/wider/shifted from row to row
    (detection noise); column 1's are similarly ragged. Every cell in a
    column must end up sharing that column's widest observed left/right
    edge, and the two columns must snap to one shared boundary instead of
    keeping their few pixels of detected overlap.
    """
    data = {
        "table_res_list": [{
            "cell_box_list": [
                [10, 10, 110, 35], [120, 10, 220, 35],
                [8, 40, 105, 65], [122, 40, 218, 65],
                [10, 70, 115, 95], [125, 70, 225, 95],
            ]
        }]
    }
    tables = parse_ppstructure_tables(data, source_id="source")
    cells = sorted(rasterize_table_columns(tables[0].cells), key=lambda cell: (cell.column_index, cell.row_index))

    column_0 = [cell for cell in cells if cell.column_index == 0]
    column_1 = [cell for cell in cells if cell.column_index == 1]
    assert {(cell.box.x1, cell.box.x2) for cell in column_0} == {(8, 117)}
    assert {(cell.box.x1, cell.box.x2) for cell in column_1} == {(117, 225)}
    # y-boundaries stay per-row -- only the shared column edges are rebuilt.
    assert [cell.box.y1 for cell in column_0] == [10, 40, 70]


def test_rasterize_table_columns_ignores_a_mis_clustered_spanning_outlier() -> None:
    """A full-width header row sharing column_index 0 with column_span==1
    must not stretch every other row in that column to its own width.

    Older localization records can lack ``column_span``, so a consumer may
    see a genuinely spanning header cell as an ordinary column_span==1 cell.
    Real production data showed exactly this: a title
    row detected at x1=1163..x2=1916 sharing column 0 with data rows whose
    boxes were all ~1163..1350-1370. Without an outlier guard, "widest
    variant" would wrongly stretch every data row in column 0 out to 1916.
    """
    header = TableCell("t", "header", 0, 0, Box(1163, 0, 1916, 20), "", 0.9)
    rows = [
        TableCell("t", f"row{i}", i, 0, Box(1163, 20 + i * 30, 1350 + i, 40 + i * 30), "", 0.9)
        for i in range(1, 6)
    ]
    cells = rasterize_table_columns([header, *rows])

    by_id = {cell.cell_id: cell for cell in cells}
    # The outlier itself is left completely untouched.
    assert by_id["header"].box == Box(1163, 0, 1916, 20)
    # Every ordinary row keeps a narrow, consistent column-0 width -- none of
    # them got stretched out to the header's 1916 right edge.
    widened_x2_values = {by_id[f"row{i}"].box.x2 for i in range(1, 6)}
    assert widened_x2_values == {1355}
    assert max(widened_x2_values) < 1916


def test_rasterize_table_columns_ignores_a_column_used_by_only_one_row() -> None:
    """A sub-header cell tagged with its own ``column_index`` in a single row
    must not wedge itself between two real, widely-shared columns and drag
    their shared boundary in to meet it.

    Real production data (RV volume table, source
    ``2ded7c62ebf9453e70edc3b1``): column 1 (the value column) is used by 8
    rows with right edges spanning up to 381; column 3 (the normal-range
    column) starts around 379-383. Column 2 exists in exactly one row -- a
    "Endo Volume" sub-header cell at 200..281, squeezed in between. Without a
    row-count floor, boundary-snapping treated column 2 as an equal neighbour
    of column 1 and pulled column 1's right edge in from 381 to ~260,
    leaving every data row in column 1 with a badly narrowed box and a wide,
    wrongly-empty gap next to it -- visible on the proefpagina's
    "Rasterisering" stage as a value cell cut off well before the normal-range
    column starts.
    """
    sub_header = TableCell("t", "sub-header", 1, 2, Box(200, 519, 281, 534), "", 0.9)
    value_boxes = {
        2: (165, 538, 377, 561), 3: (165, 561, 380, 585), 4: (165, 585, 381, 609), 5: (162, 609, 378, 633),
        6: (158, 633, 341, 657), 7: (154, 657, 332, 681), 8: (154, 681, 328, 705), 9: (158, 705, 326, 727),
    }
    normal_boxes = {
        2: (379, 538, 564, 561), 3: (381, 561, 564, 585), 4: (381, 585, 563, 609), 5: (382, 609, 558, 633),
        6: (383, 633, 560, 657), 7: (383, 657, 562, 681), 8: (381, 681, 567, 705), 9: (381, 705, 566, 727),
    }
    value_cells = [
        TableCell("t", f"value{row}", row, 1, Box(x1, y1, x2, y2), "", 0.9)
        for row, (x1, y1, x2, y2) in value_boxes.items()
    ]
    normal_cells = [
        TableCell("t", f"normal{row}", row, 3, Box(x1, y1, x2, y2), "", 0.9)
        for row, (x1, y1, x2, y2) in normal_boxes.items()
    ]
    cells = rasterize_table_columns([sub_header, *value_cells, *normal_cells])
    by_id = {cell.cell_id: cell for cell in cells}

    # The sparse sub-header column never becomes a shared column: its own
    # cell is left completely untouched, same as a width outlier.
    assert by_id["sub-header"].box == Box(200, 519, 281, 534)
    # Every value-column row shares one snapped right edge, near the widest
    # raw variant (381) -- nowhere near the ~260 the bug used to squeeze it to.
    value_x2_values = {by_id[f"value{row}"].box.x2 for row in value_boxes}
    assert len(value_x2_values) == 1
    assert value_x2_values.pop() > 350


def test_rasterize_table_columns_does_not_snap_across_an_excluded_column() -> None:
    """A column excluded as sparse (see the previous test) must still act as
    a fence between its two kept neighbours, not a column that was never
    there.

    Real production data (proefpagina sources ``faa69d10532321d8f13448a9``
    and ``2eaf574162a07b08734dca6d``): the value column's cells landed split
    across two column indices (1 and 2), each individually too sparse to
    pass the row-coverage floor, so *both* got excluded -- leaving only the
    label column (0) and the reference-range column (3) in the shared
    raster. Before this guard, ``ordered_columns`` skipped straight from 0
    to 3 and boundary-snapped them as if they were adjacent, stretching the
    label column's right edge from its own ~185px width out to 324 --
    straight across the entire (invisible, because excluded) value column.
    A later consumer then assigned the value text to the label cell too (by
    centre-point containment), gluing "228.4 ml ED Volume" into one reading
    instead of two.
    """
    label_cells = [
        TableCell("t", f"label{row}", row, 0, Box(3, 20 + row * 24, 187, 20 + row * 24 + 24), "", 0.9)
        for row in range(1, 11)
    ]
    # Column 1: a handful of wide, spanning value cells (excluded from
    # by_column entirely, since rasterize_table_columns only tracks
    # column_span==1 cells there).
    spanning_value_cells = [
        TableCell(
            "t", f"value{row}", row, 1, Box(x1, 20 + row * 24, 444, 20 + row * 24 + 24), "", 0.9,
            column_span=2,
        )
        for row, x1 in {3: 183, 4: 174, 5: 173, 6: 177, 7: 169, 8: 170}.items()
    ]
    # Column 2: a few narrow, single-span cells -- individually too sparse
    # (3 of 10 rows) to pass the row-coverage floor.
    narrow_value_cells = [
        TableCell("t", f"narrow{row}", row, 2, Box(x1, 20 + row * 24, x2, 20 + row * 24 + 24), "", 0.9)
        for row, (x1, x2) in {1: (221, 444), 2: (222, 443), 10: (221, 377)}.items()
    ]
    range_cells = [
        TableCell("t", f"range{row}", row, 3, Box(442, 20 + row * 24, 664, 20 + row * 24 + 24), "", 0.9)
        for row in range(1, 11)
    ]
    cells = rasterize_table_columns([*label_cells, *spanning_value_cells, *narrow_value_cells, *range_cells])
    by_id = {cell.cell_id: cell for cell in cells}

    # The label column keeps its own observed width -- it must never reach
    # past where the (excluded) value column's own cells actually start.
    label_x2_values = {by_id[f"label{row}"].box.x2 for row in range(1, 11)}
    assert label_x2_values == {187}
    # The range column likewise keeps its own observed width on the left.
    range_x1_values = {by_id[f"range{row}"].box.x1 for row in range(1, 11)}
    assert range_x1_values == {442}
    # Neither excluded (value) column's own cells were touched.
    for row, x1 in {3: 183, 4: 174, 5: 173, 6: 177, 7: 169, 8: 170}.items():
        assert by_id[f"value{row}"].box.x1 == x1
    for row, (x1, _x2) in {1: (221, 444), 2: (222, 443), 10: (221, 377)}.items():
        assert by_id[f"narrow{row}"].box.x1 == x1


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
