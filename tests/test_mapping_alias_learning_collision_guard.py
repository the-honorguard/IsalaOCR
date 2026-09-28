"""Confirming a mapping must never learn an alias already claimed by a
*different* field (``TrainingDatabase._upsert_mapping_in_connection``,
db_mappings.py).

Before this fix, every confirmed mapping blindly appended the observed
label's raw text to that field's ``aliases_json``, with no check that the
same text wasn't already a legitimate alias of a sibling field. In
production this let "ES Volume" leak into "ED Volume/BSA"'s own alias list
(and vice versa) after a single wrong auto-confirmed match, after which both
fields registered ``exact_alias=True`` for the same relation and started
swapping values between pipeline runs (see the compound-unit fix in
application_processing/semantics.py for the other half of that bug).
"""

from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.db import TrainingDatabase


def _seed_source(database: TrainingDatabase, source_id: str, *, label: str, value: str) -> dict:
    label_block = {
        "block_id": f"{source_id}-label", "source_id": source_id, "block_type": "table_cell",
        "role": "label", "text": label, "normalized_text": label.casefold(),
        "confidence": 0.95, "x1": 10, "y1": 10, "x2": 110, "y2": 30,
        "line_index": 0, "sequence_index": 0, "parent_block_id": "", "context_text": "", "crop_path": "",
    }
    value_block = {
        "block_id": f"{source_id}-value", "source_id": source_id, "block_type": "table_cell",
        "role": "value", "text": value, "normalized_text": value.casefold(),
        "confidence": 0.95, "x1": 130, "y1": 10, "x2": 180, "y2": 30,
        "line_index": 0, "sequence_index": 1, "parent_block_id": "", "context_text": "", "crop_path": "",
    }
    relation = {
        "relation_id": f"{source_id}-relation", "source_id": source_id,
        "label_block_id": label_block["block_id"], "value_block_id": value_block["block_id"],
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95,
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
    return relation


def _aliases(database: TrainingDatabase, field_key: str) -> list[str]:
    with database.connect() as db:
        row = db.execute(
            "SELECT aliases_json FROM field_definitions WHERE field_key=?", (field_key,),
        ).fetchone()
    return json.loads(row["aliases_json"] or "[]")


def test_confirming_a_mapping_does_not_learn_an_alias_owned_by_another_field(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_field_definition(
        "lv_ed_volume_bsa", "Left ventricle ED Volume/BSA",
        preferred_unit="ml/m²", aliases=["Left ventricle ED Volume/BSA", "ES Volume"],
    )
    database.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume",
        preferred_unit="ml", aliases=["Left ventricle ES Volume"],
    )
    relation = _seed_source(database, "source-a", label="ES Volume", value="69.5 ml")

    database.upsert_mapping(
        source_id="source-a", field_key="lv_es_volume",
        relation_id=relation["relation_id"],
        label_block_id=relation["label_block_id"], value_block_id=relation["value_block_id"],
        status="confirmed", mapping_confidence=0.95,
    )

    assert "ES Volume" not in _aliases(database, "lv_es_volume"), (
        "\"ES Volume\" is already claimed by lv_ed_volume_bsa and must not also be "
        "learned for lv_es_volume, even though lv_es_volume is its rightful owner semantically -- "
        "two fields sharing one exact alias is exactly the ambiguity that caused the real swap bug"
    )
    assert _aliases(database, "lv_ed_volume_bsa") == ["Left ventricle ED Volume/BSA", "ES Volume"]


def test_confirming_a_mapping_still_learns_an_unclaimed_alias(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_field_definition(
        "lv_es_volume", "Left ventricle ES Volume", preferred_unit="ml", aliases=[],
    )
    relation = _seed_source(database, "source-b", label="ES Volume", value="69.5 ml")

    database.upsert_mapping(
        source_id="source-b", field_key="lv_es_volume",
        relation_id=relation["relation_id"],
        label_block_id=relation["label_block_id"], value_block_id=relation["value_block_id"],
        status="confirmed", mapping_confidence=0.95,
    )

    assert "ES Volume" in _aliases(database, "lv_es_volume")
