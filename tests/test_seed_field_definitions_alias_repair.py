from __future__ import annotations

import json

from isala_ocr.training.db import TrainingDatabase


def _definition(key: str, group: str, *aliases: str) -> dict:
    return {
        "field_key": key, "display_name": key, "group_name": group,
        "data_type": "decimal", "preferred_unit": "ml", "aliases": list(aliases),
    }


def _aliases(database: TrainingDatabase, key: str) -> list[str]:
    with database.connect() as db:
        row = db.execute("SELECT aliases_json FROM field_definitions WHERE field_key=?", (key,)).fetchone()
    return json.loads(row["aliases_json"])


def test_seed_removes_aliases_leaked_from_neighbouring_fields(tmp_path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    definitions = [
        _definition("lv_cardiac_density", "Left ventricle", "Cardiac Density"),
        _definition("lv_ed_volume", "Left ventricle", "ED Volume"),
        _definition("lv_es_volume", "Left ventricle", "ES Volume"),
        _definition("rv_ed_volume", "Right ventricle", "ED Volume"),
    ]
    database.seed_field_definitions(definitions)
    # Simulate the old alias-learning bug: neighbours' labels leaked in.
    with database.connect() as db:
        db.execute(
            "UPDATE field_definitions SET aliases_json=? WHERE field_key='lv_cardiac_density'",
            (json.dumps(["Cardiac Density", "ES Volume", "ED Volume", "Some Learned Label"]),),
        )
        db.execute(
            "UPDATE field_definitions SET aliases_json=? WHERE field_key='lv_ed_volume'",
            (json.dumps(["ED Volume", "ES Volume"]),),
        )

    database.seed_field_definitions(definitions)

    assert _aliases(database, "lv_cardiac_density") == ["Cardiac Density", "Some Learned Label"]
    assert _aliases(database, "lv_ed_volume") == ["ED Volume"]
    # Left/right fields legitimately share the same label.
    assert _aliases(database, "rv_ed_volume") == ["ED Volume"]
