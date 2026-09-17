from __future__ import annotations

from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.training.generic_detection import (
    detect_generic_structure,
    integrate_table_regions,
)
from isala_ocr.training.mapping_ground_truth import (
    canonical_table_regions,
    mark_canonical_geometry,
)
from isala_ocr.training.table_cell_ground_truth import add_ground_truth_cell
from isala_ocr.training.table_panels import save_panel_profile

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_gt_mapping_reconstructs_rows_text_and_table_relations(tmp_path: Path) -> None:
    source_id = "source-a"
    # Seed one minimal canonical-GT file through the public mutation API.
    # The first call requires a bootstrappable payload, so write the schema shell
    # used by table_cell_ground_truth before adding cells.
    (tmp_path / "table_cell_ground_truth.json").write_text(
        """{
  \"schema_version\": 1,
  \"type\": \"canonical_table_cell_ground_truth\",
  \"base_dataset_id\": \"test\",
  \"created_at\": \"2026-08-20T00:00:00+00:00\",
  \"updated_at\": \"2026-08-20T00:00:00+00:00\",
  \"revision\": 1,
  \"sources\": {
    \"source-a\": {
      \"source_id\": \"source-a\",
      \"split\": \"train\",
      \"review_completed\": true,
      \"review_completed_at\": \"2026-08-20T00:00:00+00:00\",
      \"cells\": []
    }
  }
}
""",
        encoding="utf-8",
    )
    add_ground_truth_cell(tmp_path, source_id, (0, 0, 90, 22), panel_id="panel-a")
    add_ground_truth_cell(tmp_path, source_id, (100, 0, 160, 22), panel_id="panel-a")
    add_ground_truth_cell(tmp_path, source_id, (0, 32, 90, 54), panel_id="panel-a")
    add_ground_truth_cell(tmp_path, source_id, (100, 32, 160, 54), panel_id="panel-a")

    tokens = [
        OCRToken("HR", 0.99, Box(10, 3, 35, 19)),
        OCRToken("75", 0.97, Box(110, 3, 140, 19)),
        OCRToken("SV", 0.98, Box(10, 35, 35, 51)),
        OCRToken("80", 0.96, Box(110, 35, 140, 51)),
    ]
    regions = canonical_table_regions(
        tmp_path,
        source_id,
        tokens,
        image_width=200,
        image_height=100,
    )
    assert len(regions) == 1
    cells = list(regions[0].cells)
    assert [(cell.row_index, cell.column_index) for cell in cells] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert [cell.text for cell in cells] == ["HR", "75", "SV", "80"]

    blocks, relations, _ = detect_generic_structure(source_id, (100, 200, 3), tokens)
    blocks, relations, structural = integrate_table_regions(source_id, blocks, relations, regions)
    blocks = mark_canonical_geometry(blocks)
    table_relations = [relation for relation in relations if relation.relation_type == "table_cell"]
    assert len(table_relations) == 2
    assert structural["table_relation_count"] == 2
    assert any(block.geometry_source == "canonical_gt_cell" for block in blocks if block.block_type == "table_cell")


def test_canonical_gt_mapping_partitions_cells_by_configured_panel(tmp_path: Path) -> None:
    """Two side-by-side panels must become two table regions, not one.

    GT Studio review never records panel_id/panel_name on a cell (every real
    GT cell has an empty panel_id), so grouping cells by that field alone
    merged every panel's cells into a single "unassigned" TableRegion with
    one table_id - row/column clustering then ran across both panels
    together, and any later per-table panel-context match could only ever
    resolve one side for every relation in the merged region. Table/Panel
    Setup's own configured geometry must partition cells into one region per
    panel instead.
    """
    source_id = "source-lr"
    (tmp_path / "table_cell_ground_truth.json").write_text(
        """{
  \"schema_version\": 1,
  \"type\": \"canonical_table_cell_ground_truth\",
  \"base_dataset_id\": \"test\",
  \"created_at\": \"2026-08-20T00:00:00+00:00\",
  \"updated_at\": \"2026-08-20T00:00:00+00:00\",
  \"revision\": 1,
  \"sources\": {
    \"source-lr\": {
      \"source_id\": \"source-lr\",
      \"split\": \"train\",
      \"review_completed\": true,
      \"review_completed_at\": \"2026-08-20T00:00:00+00:00\",
      \"cells\": []
    }
  }
}
""",
        encoding="utf-8",
    )
    # Left ("Links") table at x=[0,160), right ("Rechts") table at
    # x=[200,360) - as GT Studio review actually produces them, with no
    # panel_id/panel_name at all.
    add_ground_truth_cell(tmp_path, source_id, (0, 0, 90, 22))
    add_ground_truth_cell(tmp_path, source_id, (100, 0, 160, 22))
    add_ground_truth_cell(tmp_path, source_id, (200, 0, 290, 22))
    add_ground_truth_cell(tmp_path, source_id, (300, 0, 360, 22))
    save_panel_profile(
        tmp_path,
        panels=[
            {"panel_id": "links", "name": "Links", "x1": 0.0, "y1": 0.0, "x2": 0.5, "y2": 1.0},
            {"panel_id": "rechts", "name": "Rechts", "x1": 0.5, "y1": 0.0, "x2": 1.0, "y2": 1.0},
        ],
        reference_source_id=source_id,
        reference_width=400,
        reference_height=100,
    )

    regions = canonical_table_regions(
        tmp_path, source_id, [], image_width=400, image_height=100
    )

    assert len(regions) == 2
    table_ids = {region.table_id for region in regions}
    assert len(table_ids) == 2
    cell_counts = sorted(len(region.cells) for region in regions)
    assert cell_counts == [2, 2]


def test_mapping_action_uses_canonical_gt_runner_without_table_model_inference() -> None:
    # mapping_gt_cli.py calls the fast collector (mapping_ground_truth_fast.py),
    # not mapping_ground_truth.py directly - that module now only supplies the
    # shared canonical_table_regions()/mark_canonical_geometry() helpers, so the
    # runner-content assertions below check the module that actually runs.
    runner = (ROOT / "application/src/isala_ocr/training/mapping_ground_truth_fast.py").read_text(encoding="utf-8")
    cli = (ROOT / "application/src/isala_ocr/mapping_gt_cli.py").read_text(encoding="utf-8")
    action = (ROOT / "automation/powershell/prepare-mapping-data.ps1").read_text(encoding="utf-8")

    assert "PPStructureTableEngine" not in runner
    assert "active_table_cell_model" not in runner
    assert "_table_settings_with_active_model" not in runner
    assert '"model_inference": False' in runner
    assert "canonical_table_regions(" in runner
    assert "collect_mapping_from_canonical_gt" in cli
    assert "isala_ocr.mapping_gt_cli" in action
    assert "isala_ocr.table_first_cli" not in action
