"""A near-certain schema match must not still wait on a manual click.

Both automatic mapping paths (the per-source schema suggester and the
"mapping profile" bulk-apply) always stored their result as ``suggested``,
even when the score was effectively unambiguous (exact alias + matching
unit + high OCR confidence). Correctness is checked again when the mapped
value is delivered downstream, so nothing is gained by also forcing a human
to click "confirm" on a match this certain - only the genuinely uncertain
matches need that review. A candidate scoring at or above
``auto_confirm_score`` (default ``0.90``) is now stored already
``confirmed``; weaker matches still land as ``suggested``.
"""

from __future__ import annotations

from pathlib import Path

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import apply_mapping_profile
from isala_ocr.training.mapping_fast import suggest_mappings_fast


def _seed_source(database: TrainingDatabase, source_id: str, *, label: str, value: str, confidence: float) -> None:
    label_block = {
        "block_id": f"{source_id}-label", "source_id": source_id, "block_type": "table_cell",
        "role": "label", "text": label, "normalized_text": label.casefold(),
        "confidence": confidence, "x1": 10, "y1": 10, "x2": 110, "y2": 30,
        "line_index": 0, "sequence_index": 0, "parent_block_id": "", "context_text": "", "crop_path": "",
    }
    value_block = {
        "block_id": f"{source_id}-value", "source_id": source_id, "block_type": "table_cell",
        "role": "value", "text": value, "normalized_text": value.casefold(),
        "confidence": confidence, "x1": 130, "y1": 10, "x2": 180, "y2": 30,
        "line_index": 0, "sequence_index": 1, "parent_block_id": "", "context_text": "", "crop_path": "",
    }
    relation = {
        "relation_id": f"{source_id}-relation", "source_id": source_id,
        "label_block_id": label_block["block_id"], "value_block_id": value_block["block_id"],
        "unit_block_id": "", "relation_type": "table_cell", "confidence": confidence,
        "rank": 1, "context_text": "",
    }
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 300, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test",
            "token_count": 2,
        },
        [label_block, value_block],
        [relation],
    )


def _database(tmp_path: Path) -> TrainingDatabase:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_field_definition(
        "lv_ejection_fraction", "Ejectiefractie",
        preferred_unit="%", aliases=["Ejectiefractie", "EF"],
    )
    return database


def test_exact_alias_and_unit_match_is_stored_already_confirmed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database, "source-exact", label="Ejectiefractie", value="56 %", confidence=0.99)

    suggestions = suggest_mappings_fast(database, "source-exact")

    assert len(suggestions) == 1
    mapping = suggestions[0]
    assert mapping["field_key"] == "lv_ejection_fraction"
    assert mapping["mapping_confidence"] >= 0.90
    assert mapping["status"] == "confirmed"
    assert "auto_confirmed" in mapping["notes"]


def test_weak_match_still_requires_manual_confirmation(tmp_path: Path) -> None:
    database = _database(tmp_path)
    # Not an exact alias and no unit match: comfortably below the auto-confirm bar.
    _seed_source(database, "source-weak", label="Uitkomst hartfunctie", value="ongeveer normaal", confidence=0.7)

    suggestions = suggest_mappings_fast(database, "source-weak", minimum_score=0.1)

    assert len(suggestions) == 1
    mapping = suggestions[0]
    assert mapping["mapping_confidence"] < 0.90
    assert mapping["status"] == "suggested"


def test_mapping_profile_apply_also_auto_confirms_high_score_matches(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _seed_source(database, "source-template", label="Ejectiefractie", value="56 %", confidence=0.99)
    database.upsert_mapping(
        source_id="source-template", field_key="lv_ejection_fraction",
        relation_id="source-template-relation",
        label_block_id="source-template-label", value_block_id="source-template-value",
        status="confirmed",
    )
    profile = database.save_mapping_profile(
        profile_id="ef-profile", name="EF profiel", source_id="source-template",
    )

    _seed_source(database, "source-target", label="Ejectiefractie", value="61 %", confidence=0.99)
    # apply_mapping_profile defers to Pipeline-A ROI geometry for the value
    # block (see _pipeline_a_geometry_match); without a matching reviewed
    # annotation or localization candidate it has nothing to resolve onto and
    # every candidate is dropped regardless of score.
    database.replace_localization_detection(
        {
            "source_id": "source-target", "image_width": 300, "image_height": 100,
            "render_path": "source_renders/source-target.png",
            "detector_version": "test-localization", "token_count": 2,
        },
        [{
            "candidate_id": "source-target-roi", "source_id": "source-target",
            "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [],
            "crop_path": "", "x1": 128, "y1": 8, "x2": 182, "y2": 32,
        }],
        [],
    )
    applied = apply_mapping_profile(database, profile["profile_id"], "source-target")

    assert len(applied) == 1
    mapping = applied[0]
    assert mapping["mapping_confidence"] >= 0.90
    assert mapping["status"] == "confirmed"
    assert "auto-confirmed" in mapping["notes"]
