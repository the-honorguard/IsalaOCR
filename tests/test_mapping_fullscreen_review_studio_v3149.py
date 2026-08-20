from pathlib import Path

from isala_ocr.training.db import TrainingDatabase, utc_now


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
JS = ROOT / "application/src/isala_ocr/training/static/mapping-review-studio.js"
CSS = ROOT / "application/src/isala_ocr/training/static/mapping-review-studio.css"
VERSION = ROOT / "project/VERSION"


def test_mapping_review_studio_assets_are_loaded_globally_but_noop_off_mapping():
    base = BASE.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")

    assert "mapping-review-studio.css" in base
    assert "mapping-review-studio.js" in base
    assert '<script defer src="{{ url_for(\'static\',filename=\'mapping-review-studio.js\',v=app_version) }}"></script>' in base
    assert "const rows = Array.from(document.querySelectorAll('.mapping-relation-row'));" in js
    assert "if (!rows.length" in js


def test_mapping_review_studio_is_a_real_single_relation_review_queue():
    js = JS.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert "⛶ Review fullscreen" in js
    assert "Mapping Review Studio" in js
    assert "Alleen open / voorgesteld" in js
    assert "Goedkeuren & volgende" in js
    assert "Overslaan →" in js
    assert "Afkeuren…" in js
    assert "relation.pipeline_a_roi_ready" in js
    assert "mapping-review-field" in js
    assert "mapping-review-notes" in js
    assert "mapping-review-label-box" in js
    assert "mapping-review-value-box" in js
    assert "position: fixed" in css
    assert "inset: 0" in css
    assert "grid-template-columns: minmax(0, 1.65fr) minmax(360px, 0.75fr)" in css


def test_mapping_review_studio_has_step6_style_keyboard_and_viewer_controls():
    js = JS.read_text(encoding="utf-8")

    assert "event.key === 'Enter'" in js
    assert "event.key === 'Escape'" in js
    assert "event.key === 'ArrowRight'" in js
    assert "event.key === 'ArrowLeft'" in js
    assert "event.key === 'f' || event.key === 'F'" in js
    assert "event.code === 'Space'" in js
    assert "viewport.addEventListener('wheel'" in js
    assert "mapping-review-one-to-one" in js
    assert "focusCurrent" in js


def test_fullscreen_approval_posts_only_the_current_relation():
    js = JS.read_text(encoding="utf-8")

    assert "const body = new FormData();" in js
    assert "body.append('mapping_action', 'save');" in js
    assert "body.append('relation_id', relationId);" in js
    assert "body.append(`field_${relationId}`, sourceSelect.value);" in js
    assert "new FormData(form)" not in js


def test_partial_mapping_sync_preserves_other_suggestions(tmp_path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    now = utc_now()
    with database.connect() as db:
        db.execute(
            """INSERT INTO detection_sources(
                source_id,image_width,image_height,render_path,detector_version,
                token_count,block_count,relation_count,detected_at,updated_at,review_completed
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            ("source-1", 1000, 800, "source.png", "test", 0, 4, 2, now, now, 1),
        )
        for field_key, display_name in (("lv_ed_volume", "LV ED Volume"), ("lv_es_volume", "LV ES Volume")):
            db.execute(
                """INSERT INTO field_definitions(
                    field_key,display_name,group_name,data_type,preferred_unit,aliases_json,
                    minimum_value,maximum_value,required,active,built_in,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (field_key, display_name, "Left ventricle", "decimal", "ml", "[]", None, None, 0, 1, 1, now, now),
            )
        for block_id, text, x1 in (("label-1", "ED Volume", 10), ("value-1", "145 ml", 200), ("label-2", "ES Volume", 10), ("value-2", "60 ml", 200)):
            db.execute(
                """INSERT INTO detected_blocks(
                    block_id,source_id,block_type,role,text,normalized_text,confidence,
                    x1,y1,x2,y2,line_index,sequence_index,parent_block_id,context_text,crop_path,
                    table_id,row_index,column_index,row_span,column_span,geometry_source,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (block_id, "source-1", "table_cell", "value" if block_id.startswith("value") else "label", text, text.lower(), 0.99,
                 x1, 10 if block_id.endswith("1") else 60, x1 + 120, 45 if block_id.endswith("1") else 95,
                 0, 0, "", "Left ventricle", "", "table-lv", 0 if block_id.endswith("1") else 1,
                 1 if block_id.startswith("value") else 0, 1, 1, "canonical_gt_cell", now, now),
            )
        for relation_id, label_id, value_id, row_index in (("r1", "label-1", "value-1", 0), ("r2", "label-2", "value-2", 1)):
            db.execute(
                """INSERT INTO detected_relations(
                    relation_id,source_id,label_block_id,value_block_id,unit_block_id,relation_type,
                    confidence,rank,context_text,status,table_id,row_index,value_column_index,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (relation_id, "source-1", label_id, value_id, "", "table_cell", 0.99, 1,
                 "Left ventricle | lv", "proposed", "table-lv", row_index, 1, now, now),
            )
        for mapping_id, relation_id, field_key, label_id, value_id in (
            ("m1", "r1", "lv_ed_volume", "label-1", "value-1"),
            ("m2", "r2", "lv_es_volume", "label-2", "value-2"),
        ):
            db.execute(
                """INSERT INTO field_mappings(
                    mapping_id,source_id,relation_id,field_key,label_block_id,value_block_id,unit_block_id,
                    status,mapping_confidence,notes,profile_id,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mapping_id, "source-1", relation_id, field_key, label_id, value_id, "", "suggested", 0.95, "", "", now, now),
            )

    result = database.sync_relation_mappings(
        "source-1",
        [{"relation_id": "r1", "field_key": "lv_ed_volume", "notes": "reviewed fullscreen"}],
    )
    mappings = {item["relation_id"]: item for item in database.list_mappings("source-1")}

    assert result["saved"] == 1
    assert mappings["r1"]["status"] == "confirmed"
    assert mappings["r1"]["notes"] == "reviewed fullscreen"
    assert mappings["r2"]["status"] == "suggested"
    assert mappings["r2"]["field_key"] == "lv_es_volume"


def test_mapping_review_studio_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.14.10"
