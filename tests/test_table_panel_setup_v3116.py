from __future__ import annotations

from pathlib import Path

from isala_ocr.training.table_panels import (
    clear_panel_geometry,
    load_panel_profile,
    save_panel_definitions,
    save_panel_profile,
)

ROOT = Path(__file__).resolve().parents[1]


def test_panel_names_are_saved_separately_and_reused_by_geometry(tmp_path: Path):
    profile = save_panel_definitions(
        tmp_path,
        definitions=[
            {"name": "Left ventricle Volume Result"},
            {"name": "Right ventricle Volume Result"},
        ],
    )
    assert [item["name"] for item in profile["definitions"]] == [
        "Left ventricle Volume Result",
        "Right ventricle Volume Result",
    ]
    ids = [item["panel_id"] for item in profile["definitions"]]

    profile = save_panel_profile(
        tmp_path,
        panels=[
            {"panel_id": ids[0], "x1": .02, "y1": .05, "x2": .31, "y2": .46},
            {"panel_id": ids[1], "x1": .02, "y1": .52, "x2": .31, "y2": .94},
        ],
        reference_width=1000,
        reference_height=600,
    )
    assert [item["name"] for item in profile["panels"]] == [
        "Left ventricle Volume Result",
        "Right ventricle Volume Result",
    ]

    # A later rename changes the display name but keeps the authoritative geometry.
    profile = save_panel_definitions(
        tmp_path,
        definitions=[
            {"panel_id": ids[0], "name": "LV Volume Results"},
            {"panel_id": ids[1], "name": "RV Volume Results"},
        ],
    )
    assert len(profile["panels"]) == 2
    assert profile["panels"][0]["name"] == "LV Volume Results"
    assert profile["panels"][0]["x2"] == .31


def test_clearing_panel_geometry_keeps_one_time_names(tmp_path: Path):
    profile = save_panel_definitions(tmp_path, definitions=[{"name": "LV"}, {"name": "RV"}])
    ids = [item["panel_id"] for item in profile["definitions"]]
    save_panel_profile(
        tmp_path,
        panels=[
            {"panel_id": ids[0], "x1": .1, "y1": .1, "x2": .4, "y2": .4},
            {"panel_id": ids[1], "x1": .1, "y1": .5, "x2": .4, "y2": .9},
        ],
    )
    cleared = clear_panel_geometry(tmp_path)
    assert cleared["panels"] == []
    assert [item["name"] for item in cleared["definitions"]] == ["LV", "RV"]
    assert load_panel_profile(tmp_path)["definitions"] == cleared["definitions"]


def test_panel_setup_ui_has_one_time_names_and_post_snap_resize_handles():
    prep = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")
    panel = (ROOT / "application/src/isala_ocr/training/templates/table_panel_setup.html").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")

    assert 'id="panel-name-setup"' in prep
    assert 'id="panel-definition-save"' in prep
    assert 'CMR LV/RV standaardnamen' in prep
    assert '/api/table-panel-definitions' in prep
    assert '@app.post("/api/table-panel-definitions")' in webui

    assert 'id="panel-target"' in panel
    assert 'panel-resize-handle' in panel
    assert "['nw','n','ne','e','se','s','sw','w']" in panel
    assert 'beginResize' in panel
    assert 'Gebruik dit alleen als startpunt' in panel
    assert 'De panelnamen uit Stap 1 blijven bewaard' in panel
