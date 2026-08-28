from __future__ import annotations

from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.table_structure import parse_ppstructure_tables
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import suggest_mappings


def _seed_detection(db: TrainingDatabase) -> None:
    blocks = [
        {
            "block_id": "label-a", "source_id": "source", "block_type": "semantic", "role": "label",
            "text": "Alpha", "normalized_text": "alpha", "confidence": 0.99,
            "x1": 10, "y1": 10, "x2": 70, "y2": 30, "line_index": 0, "sequence_index": 0,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
        {
            "block_id": "value-a", "source_id": "source", "block_type": "semantic", "role": "value",
            "text": "12 ml", "normalized_text": "12 ml", "confidence": 0.99,
            "x1": 90, "y1": 10, "x2": 140, "y2": 30, "line_index": 0, "sequence_index": 1,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
        {
            "block_id": "label-b", "source_id": "source", "block_type": "semantic", "role": "label",
            "text": "Beta", "normalized_text": "beta", "confidence": 0.99,
            "x1": 10, "y1": 40, "x2": 70, "y2": 60, "line_index": 1, "sequence_index": 0,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
        {
            "block_id": "value-b", "source_id": "source", "block_type": "semantic", "role": "value",
            "text": "24 ml", "normalized_text": "24 ml", "confidence": 0.99,
            "x1": 90, "y1": 40, "x2": 140, "y2": 60, "line_index": 1, "sequence_index": 1,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
    ]
    relations = [
        {
            "relation_id": "relation-a", "source_id": "source", "label_block_id": "label-a",
            "value_block_id": "value-a", "unit_block_id": "", "relation_type": "same_line_right",
            "confidence": 0.99, "rank": 1, "context_text": "",
        },
        {
            "relation_id": "relation-b", "source_id": "source", "label_block_id": "label-b",
            "value_block_id": "value-b", "unit_block_id": "", "relation_type": "same_line_right",
            "confidence": 0.99, "rank": 1, "context_text": "",
        },
    ]
    db.replace_generic_detection(
        {
            "source_id": "source", "image_width": 200, "image_height": 100,
            "render_path": "source_renders/source.png", "detector_version": "test", "token_count": 4,
        },
        blocks,
        relations,
    )
    db.replace_localization_detection(
        {
            "source_id": "source", "image_width": 200, "image_height": 100,
            "render_path": "source_renders/source.png", "detector_version": "test-localization", "token_count": 4,
        },
        [
            {"candidate_id": "loc-value-a", "source_id": "source", "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 88, "y1": 8, "x2": 142, "y2": 32},
            {"candidate_id": "loc-value-b", "source_id": "source", "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 88, "y1": 38, "x2": 142, "y2": 62},
        ],
        [],
    )


def _approved_sample(db: TrainingDatabase, field_key: str) -> str:
    sample_id = f"source_{field_key}"
    db.upsert_sample(
        {
            "sample_id": sample_id,
            "source_id": "source",
            "profile": "generic_mapping",
            "field_key": field_key,
            "field_label": field_key,
            "crop_path": f"mapped_crops/source/{field_key}.png",
            "raw_ocr": "12 ml",
            "raw_confidence": 0.99,
            "raw_variant": "recognition_only_mapped_generic",
            "image_width": 200,
            "image_height": 100,
            "roi_x1": 90,
            "roi_y1": 10,
            "roi_x2": 140,
            "roi_y2": 30,
            "extraction_method": "mapped_generic",
            "locator_confidence": 0.99,
            "locator_label_text": "Alpha",
            "locator_version": "test",
            "crop_sha256": "old-crop",
        }
    )
    db.review_roi(sample_id, "correct")
    db.review(sample_id, "accepted", "12 ml")
    return sample_id


def test_relation_reassignment_is_one_to_one_and_retires_old_roi(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_field_definition("field.beta", "Beta", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )
    sample_id = _approved_sample(db, "field.alpha")

    db.upsert_mapping(
        source_id="source", field_key="field.beta", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )

    mappings = db.list_mappings("source")
    assert [(item["field_key"], item["relation_id"]) for item in mappings] == [("field.beta", "relation-a")]
    sample = db.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic_stale"
    assert sample["roi_review_status"] == "pending"
    assert sample["status"] == "pending"
    assert sample["exact_label"] is None


def test_confirmed_label_is_learned_as_reusable_field_alias(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )
    field = db.get_field_definition("field.alpha")
    assert field is not None
    assert "Alpha" in field["aliases"]


def test_changing_mapping_geometry_retires_existing_roi(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )
    sample_id = _approved_sample(db, "field.alpha")

    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-b",
        label_block_id="label-b", value_block_id="value-b", status="confirmed",
    )

    sample = db.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic_stale"
    assert sample["raw_variant"] == "mapping_changed"
    assert sample["roi_review_status"] == "pending"


def test_recalculating_suggestions_removes_stale_automatic_suggestions(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", aliases=["Alpha"], data_type="decimal", preferred_unit="ml")
    assert suggest_mappings(db, "source", minimum_score=0.1)
    assert db.list_mappings("source", status="suggested")

    assert suggest_mappings(db, "source", minimum_score=1.1) == []
    assert db.list_mappings("source", status="suggested") == []


def test_table_cells_fall_back_per_cell_to_internal_table_ocr() -> None:
    data = {
        "table_res_list": [
            {
                "cell_box_list": [
                    [0, 0, 100, 25], [100, 0, 200, 25],
                    [0, 25, 100, 50], [100, 25, 200, 50],
                ],
                "table_ocr_pred": {
                    "rec_texts": ["Label", "Value", "ED Volume", "106.8 ml"],
                    "rec_scores": [0.98, 0.98, 0.99, 0.99],
                    "rec_boxes": [
                        [5, 5, 70, 20], [110, 5, 170, 20],
                        [5, 30, 80, 45], [110, 30, 175, 45],
                    ],
                },
            }
        ]
    }
    # Non-empty full-page OCR exists, but it does not cover this table. v3.6.2
    # discarded the internal table OCR globally in that situation.
    unrelated = [OCRToken("Elsewhere", 0.99, Box(300, 300, 380, 320))]
    tables = parse_ppstructure_tables(data, source_id="source", fallback_tokens=unrelated)
    assert len(tables) == 1
    assert [cell.text for cell in tables[0].cells] == ["Label", "Value", "ED Volume", "106.8 ml"]


def test_overlapping_table_cells_do_not_duplicate_one_ocr_token() -> None:
    data = {
        "table_res_list": [
            {
                "cell_box_list": [
                    [0, 0, 105, 25], [95, 0, 200, 25],
                    [0, 25, 105, 50], [95, 25, 200, 50],
                ]
            }
        ]
    }
    tokens = [
        OCRToken("Label", 0.99, Box(5, 30, 70, 45)),
        OCRToken("106.8 ml", 0.99, Box(105, 30, 175, 45)),
    ]
    tables = parse_ppstructure_tables(data, source_id="source", fallback_tokens=tokens)
    assert len(tables) == 1
    texts = [cell.text for cell in tables[0].cells]
    assert sum("106.8 ml" in text for text in texts) == 1


def test_mapping_studio_has_fast_review_filters_sticky_preview_and_duplicate_guard() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "application/src/isala_ocr/training/templates/mapping_studio.html").read_text(encoding="utf-8")
    css = (root / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")
    assert 'id="mapping-filter-text"' in template
    assert 'id="mapping-show-secondary"' in template
    assert 'id="mapping-filter-confidence"' in template
    assert 'id="mapping-preview-next"' in template and 'Alt+↑/↓' in template
    assert 'id="mapping-duplicate-warning"' in template
    assert 'id="preview-label-box"' in template and 'id="preview-value-box"' in template
    assert 'JSON-pad' in template
    assert '.mapping-output-preview{position:sticky' in css


def test_mappingstudio_bulk_save_is_atomic_when_one_assignment_is_invalid(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_field_definition("field.beta", "Beta", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )
    sample_id = _approved_sample(db, "field.alpha")

    try:
        db.sync_relation_mappings(
            "source",
            [
                {"relation_id": "relation-a", "field_key": "", "notes": ""},
                {"relation_id": "relation-b", "field_key": "field.does-not-exist", "notes": ""},
            ],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid bulk mapping should have failed")

    mappings = db.list_mappings("source")
    assert [(item["field_key"], item["relation_id"]) for item in mappings] == [("field.alpha", "relation-a")]
    sample = db.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic"
    assert sample["roi_review_status"] == "correct"


def test_manual_mapping_cannot_reuse_one_observed_value_for_two_output_fields(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_field_definition("field.beta", "Beta", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", value_block_id="value-a",
        label_block_id="label-a", status="confirmed",
    )
    sample_id = _approved_sample(db, "field.alpha")

    db.upsert_mapping(
        source_id="source", field_key="field.beta", value_block_id="value-a",
        label_block_id="label-a", status="confirmed",
    )

    mappings = db.list_mappings("source")
    assert [(item["field_key"], item["value_block_id"]) for item in mappings] == [("field.beta", "value-a")]
    sample = db.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic_stale"


def test_detection_geometry_change_reopens_mapping_and_retires_old_roi(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_detection(db)
    db.upsert_field_definition("field.alpha", "Alpha", data_type="decimal", preferred_unit="ml")
    db.upsert_mapping(
        source_id="source", field_key="field.alpha", relation_id="relation-a",
        label_block_id="label-a", value_block_id="value-a", status="confirmed",
    )
    sample_id = _approved_sample(db, "field.alpha")

    changed_blocks = [
        {
            "block_id": "label-new", "source_id": "source", "block_type": "semantic", "role": "label",
            "text": "Alpha", "normalized_text": "alpha", "confidence": 0.99,
            "x1": 12, "y1": 10, "x2": 72, "y2": 30, "line_index": 0, "sequence_index": 0,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
        {
            "block_id": "value-new", "source_id": "source", "block_type": "semantic", "role": "value",
            "text": "12 ml", "normalized_text": "12 ml", "confidence": 0.99,
            "x1": 94, "y1": 10, "x2": 144, "y2": 30, "line_index": 0, "sequence_index": 1,
            "parent_block_id": "", "context_text": "", "crop_path": "",
        },
    ]
    changed_relations = [
        {
            "relation_id": "relation-new", "source_id": "source", "label_block_id": "label-new",
            "value_block_id": "value-new", "unit_block_id": "", "relation_type": "same_line_right",
            "confidence": 0.99, "rank": 1, "context_text": "",
        }
    ]
    db.replace_generic_detection(
        {
            "source_id": "source", "image_width": 200, "image_height": 100,
            "render_path": "source_renders/source.png", "detector_version": "test-v2", "token_count": 2,
        },
        changed_blocks,
        changed_relations,
    )

    assert db.list_mappings("source") == []
    sample = db.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic_stale"
    assert sample["roi_review_status"] == "pending"
