from __future__ import annotations

from pathlib import Path

from isala_ocr.training.db import SCHEMA_VERSION, TrainingDatabase
from isala_ocr.training.mapping import suggest_mappings
from isala_ocr.training.relation_feedback import RELATION_FEEDBACK_REASONS


def _seed_relation(
    db: TrainingDatabase,
    *,
    source_id: str = "source-a",
    relation_id: str = "relation-a",
    label_text: str = "ES Volume ED Volume/BSA",
    value_text: str = "71.5 ml",
    x_offset: int = 0,
) -> None:
    blocks = [
        {
            "block_id": f"{source_id}-label", "source_id": source_id,
            "block_type": "semantic", "role": "label", "text": label_text,
            "normalized_text": label_text.lower(), "confidence": 0.98,
            "x1": 10 + x_offset, "y1": 10, "x2": 180 + x_offset, "y2": 52,
            "line_index": 0, "sequence_index": 0, "parent_block_id": "",
            "context_text": "Left ventricle Volume Result", "crop_path": "",
        },
        {
            "block_id": f"{source_id}-value", "source_id": source_id,
            "block_type": "semantic", "role": "value", "text": value_text,
            "normalized_text": value_text.lower(), "confidence": 0.99,
            "x1": 205 + x_offset, "y1": 12, "x2": 275 + x_offset, "y2": 31,
            "line_index": 0, "sequence_index": 1, "parent_block_id": "",
            "context_text": "Left ventricle Volume Result", "crop_path": "",
        },
    ]
    relations = [
        {
            "relation_id": relation_id, "source_id": source_id,
            "label_block_id": f"{source_id}-label", "value_block_id": f"{source_id}-value",
            "unit_block_id": "", "relation_type": "same_line_right", "confidence": 0.92,
            "rank": 1, "context_text": "Left ventricle Volume Result",
        }
    ]
    db.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 600, "image_height": 200,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test",
            "token_count": 2,
        },
        blocks,
        relations,
    )


def test_relation_rejection_is_structured_and_removes_existing_mapping(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    assert SCHEMA_VERSION >= 10
    _seed_relation(db)
    db.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume", aliases=["ES Volume"],
        data_type="decimal", preferred_unit="ml",
    )
    db.upsert_mapping(
        source_id="source-a", field_key="lv_es_volume", relation_id="relation-a",
        label_block_id="source-a-label", value_block_id="source-a-value", status="confirmed",
    )
    assert db.list_mappings("source-a")

    feedback = db.record_relation_feedback(
        source_id="source-a", relation_id="relation-a", verdict="rejected",
        reason_code="multi_row_label", reason_detail="Twee tabelrijen samengevoegd",
    )

    assert feedback["reason_code"] == "multi_row_label"
    assert db.list_mappings("source-a") == []
    relation = db.get_detected_relation("relation-a")
    assert relation is not None and relation["status"] == "rejected"
    examples = db.list_relation_feedback()
    assert len(examples) == 1
    assert examples[0]["verdict"] == "rejected"
    assert examples[0]["reason_detail"] == "Twee tabelrijen samengevoegd"


def test_rejected_relation_is_not_suggested_and_survives_redetection(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_relation(db)
    db.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume",
        aliases=["ES Volume ED Volume/BSA"], data_type="decimal", preferred_unit="ml",
    )
    db.record_relation_feedback(
        source_id="source-a", relation_id="relation-a", verdict="rejected",
        reason_code="multi_row_label",
    )
    assert suggest_mappings(db, "source-a", minimum_score=0.1) == []

    # A fresh detection pass recreates relation rows, but the durable pattern
    # signature restores the rejection instead of forgetting user feedback.
    _seed_relation(db)
    relation = db.get_detected_relation("relation-a")
    assert relation is not None and relation["status"] == "rejected"
    assert suggest_mappings(db, "source-a", minimum_score=0.1) == []


def test_rejected_pattern_influences_same_failure_on_another_source(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_relation(db, source_id="source-a", relation_id="relation-a")
    db.record_relation_feedback(
        source_id="source-a", relation_id="relation-a", verdict="rejected",
        reason_code="multi_row_label",
    )

    _seed_relation(db, source_id="source-b", relation_id="relation-b", value_text="68.2 ml")
    db.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume",
        aliases=["ES Volume ED Volume/BSA"], data_type="decimal", preferred_unit="ml",
    )
    assert suggest_mappings(db, "source-b", minimum_score=0.1) == []


def test_confirmed_relation_is_kept_as_positive_feedback_example(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_relation(db, label_text="ES Volume")
    db.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume", aliases=["ES Volume"],
        data_type="decimal", preferred_unit="ml",
    )
    db.upsert_mapping(
        source_id="source-a", field_key="lv_es_volume", relation_id="relation-a",
        label_block_id="source-a-label", value_block_id="source-a-value", status="confirmed",
    )
    examples = db.list_relation_feedback()
    assert len(examples) == 1
    assert examples[0]["verdict"] == "accepted"
    stats = db.relation_feedback_stats()
    assert stats["accepted"] == 1 and stats["rejected"] == 0


def test_mappingstudio_exposes_reject_reason_feedback_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    template = (root / "application/src/isala_ocr/training/templates/mapping_studio.html").read_text(encoding="utf-8")
    css = (root / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")

    assert "Afkeuren…" in template
    assert "Afkeuren & leren" in template
    assert 'id="mapping-reject-reason"' in template
    assert "Als alleen het <strong>functionele veld</strong> verkeerd is" in template
    assert "mapping-restore-button" in template
    assert "Feedbackleren actief" in template
    for reason_code in RELATION_FEEDBACK_REASONS:
        assert reason_code in webui or "feedback_reasons" in template
    assert "/relation-feedback" in webui
    assert ".mapping-relation-row.mapping-rejected" in css
