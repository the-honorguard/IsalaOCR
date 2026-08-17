from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase


def test_database_reopen_uses_schema_fast_path(tmp_path: Path) -> None:
    path = tmp_path / "samples.sqlite3"
    db = TrainingDatabase(path)
    with db.connect() as connection:
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_migrated_at', 'sentinel')"
        )

    TrainingDatabase(path)

    with db.connect() as connection:
        value = connection.execute(
            "SELECT value FROM metadata WHERE key='schema_migrated_at'"
        ).fetchone()[0]
    assert value == "sentinel"


def test_database_context_rolls_back_on_exception(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")

    with pytest.raises(RuntimeError):
        with db.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('rollback_probe', 'should-not-commit')"
            )
            raise RuntimeError("force rollback")

    with db.connect() as connection:
        row = connection.execute(
            "SELECT value FROM metadata WHERE key='rollback_probe'"
        ).fetchone()
    assert row is None


def test_mapped_sample_counts_are_aggregated_in_sqlite(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    now = "2026-08-12T08:00:00+00:00"
    with db.connect() as connection:
        for index, (variant, roi_status) in enumerate(
            [
                ("awaiting_value_recognition", "correct"),
                ("recognized", "correct"),
                ("recognized", "pending"),
            ]
        ):
            connection.execute(
                """
                INSERT INTO samples(
                    sample_id, source_id, profile, field_key, field_label, crop_path,
                    raw_ocr, raw_confidence, raw_variant, status, image_width, image_height,
                    roi_x1, roi_y1, roi_x2, roi_y2, extraction_method, roi_review_status,
                    created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    f"sample-{index}", f"source-{index}", "test", f"field-{index}", f"Field {index}",
                    f"crop-{index}.png", "1", 0.9, variant, "pending", 100, 100,
                    0, 0, 10, 10, "mapped_generic", roi_status, now, now,
                ),
            )
    assert db.mapped_sample_counts() == {
        "total": 3,
        "awaiting_recognition": 1,
        "recognized": 2,
        "roi_correct": 2,
    }
