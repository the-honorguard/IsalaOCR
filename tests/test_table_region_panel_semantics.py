from isala_ocr.training.table_panels import save_panel_definitions, save_panel_profile
from isala_ocr.training.table_region_ground_truth import (
    list_table_region_sources,
    list_table_regions,
    save_table_regions,
)


def test_region_gt_stays_semantic_free_while_downstream_gets_panel_roles(tmp_path):
    save_table_regions(
        tmp_path,
        "source-1",
        image_width=1000,
        image_height=500,
        regions=[
            {"x1": 50, "y1": 50, "x2": 450, "y2": 450, "name": "LV"},
            {"x1": 550, "y1": 50, "x2": 950, "y2": 450, "name": "RV"},
        ],
    )

    raw_before = list_table_region_sources(tmp_path)[0]["regions"]
    assert [item["label"] for item in raw_before] == ["table", "table"]
    assert all("panel_id" not in item and "table_id" not in item for item in raw_before)

    save_panel_definitions(
        tmp_path,
        definitions=[
            {"panel_id": "left", "name": "Links"},
            {"panel_id": "right", "name": "Rechts"},
        ],
    )
    save_panel_profile(
        tmp_path,
        reference_source_id="source-1",
        reference_width=1000,
        reference_height=500,
        panels=[
            {"panel_id": "left", "name": "Links", "x1": 0.05, "y1": 0.10, "x2": 0.45, "y2": 0.90},
            {"panel_id": "right", "name": "Rechts", "x1": 0.55, "y1": 0.10, "x2": 0.95, "y2": 0.90},
        ],
    )

    downstream = list_table_regions(tmp_path, "source-1")
    assert [item["panel_id"] for item in downstream] == ["left", "right"]
    assert [item["table_id"] for item in downstream] == ["left", "right"]
    assert [item["panel_name"] for item in downstream] == ["Links", "Rechts"]

    raw_after = list_table_region_sources(tmp_path)[0]["regions"]
    assert [item["label"] for item in raw_after] == ["table", "table"]
    assert all("panel_id" not in item and "table_id" not in item for item in raw_after)
