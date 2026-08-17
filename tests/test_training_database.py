from pathlib import Path

import pytest

from isala_ocr.training.db import TrainingDatabase, validate_exact_label


def _sample(sample_id: str = "source_field") -> dict:
    return {
        "sample_id": sample_id,
        "source_id": "source",
        "profile": "profile",
        "field_key": "field",
        "field_label": "Field",
        "crop_path": "crops/original/source/field.png",
        "raw_ocr": "12O.7 mI",
        "raw_confidence": 0.73,
        "raw_variant": "recognition_only_original_crop",
        "image_width": 100,
        "image_height": 50,
        "roi_x1": 1,
        "roi_y1": 2,
        "roi_x2": 90,
        "roi_y2": 40,
    }


def test_exact_label_is_preserved_byte_for_byte(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(_sample())
    exact = "  120,7 mI  "
    database.review("source_field", "accepted", exact, "verbatim")

    stored = database.get("source_field")
    assert stored is not None
    assert stored["exact_label"] == exact
    assert stored["raw_ocr"] == "12O.7 mI"


def test_exact_label_rejects_dataset_delimiters_only():
    assert validate_exact_label("1O0,0 mI") == "1O0,0 mI"
    for invalid in ("a\tb", "a\nb", "a\rb", "a\x00b"):
        with pytest.raises(ValueError):
            validate_exact_label(invalid)


def test_refreshing_crop_does_not_overwrite_review(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(_sample())
    database.review("source_field", "accepted", "120.7 ml", "checked")
    changed = _sample()
    changed["raw_ocr"] = "120.7 mI"
    changed["raw_confidence"] = 0.95
    assert database.upsert_sample(changed) is False

    stored = database.get("source_field")
    assert stored is not None
    assert stored["exact_label"] == "120.7 ml"
    assert stored["status"] == "accepted"
    assert stored["notes"] == "checked"
    assert stored["raw_ocr"] == "120.7 mI"


def test_confidence_and_ocr_content_filters(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")

    text_low = _sample("source_text_low")
    text_low["source_id"] = "source-text-low"
    text_low["raw_ocr"] = "89.1 ml/m²"
    text_low["raw_confidence"] = 0.61
    database.upsert_sample(text_low)

    text_high = _sample("source_text_high")
    text_high["source_id"] = "source-text-high"
    text_high["raw_ocr"] = "89.1 ml/m²"
    text_high["raw_confidence"] = 0.94
    database.upsert_sample(text_high)

    blank = _sample("source_blank")
    blank["source_id"] = "source-blank"
    blank["raw_ocr"] = ""
    blank["raw_confidence"] = 0.0
    database.upsert_sample(blank)

    missing = _sample("source_missing")
    missing["source_id"] = "source-missing"
    missing["raw_ocr"] = "-"
    missing["raw_confidence"] = 0.45
    database.upsert_sample(missing)

    uncertain_text = database.list_samples(max_confidence=0.8, ocr_content="text")
    assert [row["sample_id"] for row in uncertain_text] == ["source_text_low"]

    empty_or_missing = database.list_samples(ocr_content="blank_or_missing")
    assert {row["sample_id"] for row in empty_or_missing} == {"source_blank", "source_missing"}

    high_confidence = database.list_samples(min_confidence=0.8, ocr_content="text")
    assert [row["sample_id"] for row in high_confidence] == ["source_text_high"]


def test_no_value_status_is_not_accepted_training_data(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(_sample())
    database.review("source_field", "no_value", None, "field was empty")

    stored = database.get("source_field")
    assert stored is not None
    assert stored["status"] == "no_value"
    assert stored["exact_label"] is None
    assert database.accepted() == []
    assert database.counts()["no_value"] == 1


def test_changed_dynamic_crop_invalidates_previous_review(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    first = _sample()
    first.update({
        "crop_sha256": "aaa",
        "extraction_method": "fixed_roi",
        "locator_confidence": 0.0,
        "locator_label_text": "",
        "locator_version": "fixed-roi-v1",
    })
    database.upsert_sample(first)
    database.review("source_field", "accepted", "120.7 ml", "checked")

    changed = dict(first)
    changed.update({
        "crop_sha256": "bbb",
        "extraction_method": "dynamic_token_box",
        "locator_confidence": 0.98,
        "locator_label_text": "ED Volume",
        "locator_version": "label-row-v1",
    })
    database.upsert_sample(changed)
    stored = database.get("source_field")
    assert stored is not None
    assert stored["status"] == "pending"
    assert stored["exact_label"] is None
    assert stored["review_generation"] == 1


def test_placeholder_is_accepted_with_separate_content_class(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(_sample())
    database.review("source_field", "accepted", "-", content_class="placeholder")
    stored = database.get("source_field")
    assert stored is not None
    assert stored["status"] == "accepted"
    assert stored["content_class"] == "placeholder"
    assert stored["exact_label"] == "-"


def test_excluding_current_sample_prevents_review_queue_loop(tmp_path: Path):
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(_sample("source_field"))
    other = _sample("source_other")
    other["source_id"] = "source-other"
    database.upsert_sample(other)
    rows = database.list_samples(status="pending", exclude_sample_id="source_field")
    assert [row["sample_id"] for row in rows] == ["source_other"]


def test_schema_v2_database_is_migrated_without_losing_reviews(tmp_path: Path):
    import sqlite3

    path = tmp_path / "samples.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key, value) VALUES('schema_version', '2');
        CREATE TABLE samples (
            sample_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            profile TEXT NOT NULL,
            field_key TEXT NOT NULL,
            field_label TEXT NOT NULL,
            crop_path TEXT NOT NULL,
            raw_ocr TEXT NOT NULL DEFAULT '',
            raw_confidence REAL NOT NULL DEFAULT 0,
            raw_variant TEXT NOT NULL DEFAULT 'original',
            status TEXT NOT NULL DEFAULT 'pending',
            exact_label TEXT,
            notes TEXT NOT NULL DEFAULT '',
            image_width INTEGER NOT NULL,
            image_height INTEGER NOT NULL,
            roi_x1 INTEGER NOT NULL,
            roi_y1 INTEGER NOT NULL,
            roi_x2 INTEGER NOT NULL,
            roi_y2 INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(source_id, field_key)
        );
        INSERT INTO samples(
            sample_id, source_id, profile, field_key, field_label, crop_path,
            raw_ocr, raw_confidence, raw_variant, status, exact_label, notes,
            image_width, image_height, roi_x1, roi_y1, roi_x2, roi_y2,
            created_at, updated_at, reviewed_at
        ) VALUES(
            'source_field', 'source', 'profile', 'field', 'Field',
            'crops/original/source/field.png', '12O.7 mI', 0.73,
            'recognition_only_original_crop', 'accepted', '120.7 ml', 'checked',
            100, 50, 1, 2, 90, 40,
            '2026-08-03T00:00:00+00:00', '2026-08-03T00:00:00+00:00',
            '2026-08-03T00:00:00+00:00'
        );
        """
    )
    db.commit()
    db.close()

    migrated = TrainingDatabase(path)
    stored = migrated.get("source_field")
    assert stored is not None
    assert stored["status"] == "accepted"
    assert stored["exact_label"] == "120.7 ml"
    assert stored["notes"] == "checked"
    assert stored["extraction_method"] == "fixed_roi"
    assert stored["content_class"] == "unknown"
    assert stored["review_generation"] == 0

    with sqlite3.connect(path) as check:
        version = check.execute(
            "SELECT value FROM metadata WHERE key='schema_version'"
        ).fetchone()[0]
        method_index = check.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_samples_method'"
        ).fetchone()
    assert version == "13"
    assert method_index is not None
    assert (tmp_path / "samples.before-schema-v13.sqlite3").is_file()


def test_partial_failed_v3_schema_is_repaired_idempotently(tmp_path: Path):
    import sqlite3

    path = tmp_path / "samples.sqlite3"
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key, value) VALUES('schema_version', '2');
        CREATE TABLE samples (
            sample_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            profile TEXT NOT NULL,
            field_key TEXT NOT NULL,
            field_label TEXT NOT NULL,
            crop_path TEXT NOT NULL,
            raw_ocr TEXT NOT NULL DEFAULT '',
            raw_confidence REAL NOT NULL DEFAULT 0,
            raw_variant TEXT NOT NULL DEFAULT 'original',
            status TEXT NOT NULL DEFAULT 'pending',
            exact_label TEXT,
            notes TEXT NOT NULL DEFAULT '',
            image_width INTEGER NOT NULL,
            image_height INTEGER NOT NULL,
            roi_x1 INTEGER NOT NULL,
            roi_y1 INTEGER NOT NULL,
            roi_x2 INTEGER NOT NULL,
            roi_y2 INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reviewed_at TEXT,
            UNIQUE(source_id, field_key)
        );
        CREATE TABLE review_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_id TEXT NOT NULL,
            status TEXT NOT NULL,
            exact_label TEXT,
            notes TEXT NOT NULL DEFAULT '',
            content_class TEXT NOT NULL DEFAULT 'unknown',
            crop_sha256 TEXT NOT NULL DEFAULT '',
            reviewed_at TEXT,
            invalidated_at TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        CREATE INDEX idx_samples_status ON samples(status);
        CREATE INDEX idx_samples_source ON samples(source_id);
        CREATE INDEX idx_samples_field ON samples(field_key);
        CREATE INDEX idx_samples_confidence ON samples(raw_confidence);
        """
    )
    db.commit()
    db.close()

    TrainingDatabase(path)
    TrainingDatabase(path)
    with sqlite3.connect(path) as check:
        columns = {row[1] for row in check.execute("PRAGMA table_info(samples)")}
        indexes = {row[1] for row in check.execute("PRAGMA index_list(samples)")}
    assert "extraction_method" in columns
    assert "crop_sha256" in columns
    assert "idx_samples_method" in indexes
