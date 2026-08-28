from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .relation_feedback import (
    RELATION_FEEDBACK_REASONS, VALID_RELATION_FEEDBACK_VERDICTS,
    relation_signature, relation_snapshot,
)

SCHEMA_VERSION = 14
VALID_STATUSES = {"pending", "accepted", "unreadable", "roi_error", "excluded", "no_value"}
VALID_CONTENT_CLASSES = {"unknown", "value", "no_value", "placeholder"}
VALID_OCR_CONTENT_FILTERS = {"all", "text", "blank", "missing", "blank_or_missing"}
VALID_HEADER_REVIEW_STATUSES = {"pending", "accepted", "rejected", "deferred"}
VALID_MAPPING_STATUSES = {"suggested", "confirmed", "rejected"}
VALID_DETECTION_REVIEW_STATUSES = {"correct", "adjusted", "rejected", "added"}
VALID_DETECTION_REVIEW_REASONS = {"", "too_small", "too_large", "misplaced", "false_positive", "merged_fields", "split_field", "table_geometry_error", "other"}
VALID_DETECTION_RELEVANCE_STATUSES = {"unreviewed", "relevant", "irrelevant"}
VALID_DETECTION_RELEVANCE_REASONS = {"", "date_time", "ui_element", "reference_value", "graph_annotation", "technical_overlay", "study_info_out_of_scope", "other_out_of_scope"}
VALID_DETECTION_TRAINING_ROLES = {"positive", "negative"}
VALID_FIELD_TYPES = {"text", "decimal", "integer", "boolean", "date", "code"}
MISSING_MARKERS = ("-", "–", "—")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_exact_label(label: str) -> str:
    """Validate a verbatim label without changing it."""
    if any(char in label for char in ("\t", "\r", "\n", "\x00")):
        raise ValueError("Exact labels may not contain tabs, line breaks or NUL characters")
    return label


class TrainingDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initializing = False
        self.initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # The project reset may remove the SQLite file while the long-lived
        # WebUI process is still running. Recreate the schema before opening a
        # new connection instead of allowing every request to fail with
        # "no such table".
        if not self._initializing and not self._schema_is_current():
            self.initialize()
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @classmethod
    def _ensure_columns(cls, db: sqlite3.Connection) -> None:
        additions = {
            "extraction_method": "TEXT NOT NULL DEFAULT 'fixed_roi'",
            "locator_confidence": "REAL NOT NULL DEFAULT 0",
            "locator_label_text": "TEXT NOT NULL DEFAULT ''",
            "locator_version": "TEXT NOT NULL DEFAULT ''",
            "crop_sha256": "TEXT NOT NULL DEFAULT ''",
            "content_class": "TEXT NOT NULL DEFAULT 'unknown'",
            "review_generation": "INTEGER NOT NULL DEFAULT 0",
            "roi_review_status": "TEXT NOT NULL DEFAULT 'pending'",
            "roi_review_notes": "TEXT NOT NULL DEFAULT ''",
            "roi_reviewed_at": "TEXT",
            "locator_label_x1": "INTEGER NOT NULL DEFAULT -1",
            "locator_label_y1": "INTEGER NOT NULL DEFAULT -1",
            "locator_label_x2": "INTEGER NOT NULL DEFAULT -1",
            "locator_label_y2": "INTEGER NOT NULL DEFAULT -1",
            "header_crop_path": "TEXT NOT NULL DEFAULT ''",
            "header_crop_sha256": "TEXT NOT NULL DEFAULT ''",
            "header_review_status": "TEXT NOT NULL DEFAULT 'pending'",
            "header_target_field_key": "TEXT NOT NULL DEFAULT ''",
            "header_exact_label": "TEXT NOT NULL DEFAULT ''",
            "header_review_notes": "TEXT NOT NULL DEFAULT ''",
            "header_reviewed_at": "TEXT",
        }
        existing = cls._column_names(db, "samples")
        for name, definition in additions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE samples ADD COLUMN {name} {definition}")

    @classmethod
    def _ensure_review_history_columns(cls, db: sqlite3.Connection) -> None:
        additions = {
            "content_class": "TEXT NOT NULL DEFAULT 'unknown'",
            "crop_sha256": "TEXT NOT NULL DEFAULT ''",
            "reviewed_at": "TEXT",
            "invalidated_at": "TEXT NOT NULL DEFAULT ''",
            "reason": "TEXT NOT NULL DEFAULT 'legacy_migration'",
        }
        existing = cls._column_names(db, "review_history")
        for name, definition in additions.items():
            if name not in existing:
                db.execute(f"ALTER TABLE review_history ADD COLUMN {name} {definition}")


    @classmethod
    def _ensure_detection_columns(cls, db: sqlite3.Connection) -> None:
        block_additions = {
            "table_id": "TEXT NOT NULL DEFAULT ''",
            "row_index": "INTEGER NOT NULL DEFAULT -1",
            "column_index": "INTEGER NOT NULL DEFAULT -1",
            "row_span": "INTEGER NOT NULL DEFAULT 1",
            "column_span": "INTEGER NOT NULL DEFAULT 1",
            "geometry_source": "TEXT NOT NULL DEFAULT 'ocr'",
            "recognition_text": "TEXT NOT NULL DEFAULT ''",
            "recognition_confidence": "REAL NOT NULL DEFAULT 0",
            "recognition_model": "TEXT NOT NULL DEFAULT ''",
        }
        existing_blocks = cls._column_names(db, "detected_blocks")
        for name, definition in block_additions.items():
            if name not in existing_blocks:
                db.execute(f"ALTER TABLE detected_blocks ADD COLUMN {name} {definition}")
        relation_additions = {
            "table_id": "TEXT NOT NULL DEFAULT ''",
            "row_index": "INTEGER NOT NULL DEFAULT -1",
            "value_column_index": "INTEGER NOT NULL DEFAULT -1",
        }
        existing_relations = cls._column_names(db, "detected_relations")
        for name, definition in relation_additions.items():
            if name not in existing_relations:
                db.execute(f"ALTER TABLE detected_relations ADD COLUMN {name} {definition}")

        review_additions = {
            "relevance_status": "TEXT NOT NULL DEFAULT 'relevant'",
            "relevance_reason": "TEXT NOT NULL DEFAULT ''",
        }
        existing_reviews = cls._column_names(db, "detection_reviews")
        for name, definition in review_additions.items():
            if name not in existing_reviews:
                db.execute(f"ALTER TABLE detection_reviews ADD COLUMN {name} {definition}")

        annotation_additions = {
            "training_role": "TEXT NOT NULL DEFAULT 'positive'",
        }
        existing_annotations = cls._column_names(db, "detection_annotations")
        for name, definition in annotation_additions.items():
            if name not in existing_annotations:
                db.execute(f"ALTER TABLE detection_annotations ADD COLUMN {name} {definition}")

        source_additions = {
            "review_completed": "INTEGER NOT NULL DEFAULT 0",
            "review_completed_at": "TEXT",
        }
        existing_sources = cls._column_names(db, "detection_sources")
        for name, definition in source_additions.items():
            if name not in existing_sources:
                db.execute(f"ALTER TABLE detection_sources ADD COLUMN {name} {definition}")

    def _backup_before_migration(self) -> Path | None:
        """Create one SQLite-consistent backup before changing an existing schema."""
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return None
        source = sqlite3.connect(self.path, timeout=30)
        source.row_factory = sqlite3.Row
        try:
            table = source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='samples'"
            ).fetchone()
            if table is None:
                return None
            existing = {
                str(row["name"])
                for row in source.execute("PRAGMA table_info(samples)").fetchall()
            }
            required = {
                "extraction_method",
                "locator_confidence",
                "locator_label_text",
                "locator_version",
                "crop_sha256",
                "content_class",
                "review_generation",
                "header_review_status",
                "header_target_field_key",
                "header_crop_path",
            }
            version_row = source.execute(
                "SELECT value FROM metadata WHERE key='schema_version'"
            ).fetchone() if source.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'"
            ).fetchone() else None
            version = int(version_row[0]) if version_row and str(version_row[0]).isdigit() else 0
            if required.issubset(existing) and version >= SCHEMA_VERSION:
                return None

            backup = self.path.with_name(
                f"{self.path.stem}.before-schema-v{SCHEMA_VERSION}{self.path.suffix}"
            )
            if backup.exists():
                return backup
            destination = sqlite3.connect(backup, timeout=30)
            try:
                source.backup(destination)
            finally:
                destination.close()
            return backup
        finally:
            source.close()

    def _schema_is_current(self) -> bool:
        """Fast path for already initialized databases.

        Schema migrations set PRAGMA user_version only as their final step, so a
        matching version means the expensive CREATE/ALTER/index migration path
        has completed successfully before.
        """
        if not self.path.is_file() or self.path.stat().st_size == 0:
            return False
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            row = connection.execute("PRAGMA user_version").fetchone()
            return bool(row and int(row[0]) >= SCHEMA_VERSION)
        except (sqlite3.DatabaseError, TypeError, ValueError):
            return False
        finally:
            connection.close()

    def initialize(self) -> None:
        if self._schema_is_current():
            return
        self._initializing = True
        try:
            self._backup_before_migration()
            with self.connect() as db:
                # Tables must exist before ALTER TABLE migrations. Indexes that use
                # new columns are intentionally created only after those migrations.
                db.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS samples (
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
                        extraction_method TEXT NOT NULL DEFAULT 'fixed_roi',
                        locator_confidence REAL NOT NULL DEFAULT 0,
                        locator_label_text TEXT NOT NULL DEFAULT '',
                        locator_version TEXT NOT NULL DEFAULT '',
                        crop_sha256 TEXT NOT NULL DEFAULT '',
                        content_class TEXT NOT NULL DEFAULT 'unknown',
                        review_generation INTEGER NOT NULL DEFAULT 0,
                        roi_review_status TEXT NOT NULL DEFAULT 'pending',
                        roi_review_notes TEXT NOT NULL DEFAULT '',
                        roi_reviewed_at TEXT,
                        locator_label_x1 INTEGER NOT NULL DEFAULT -1,
                        locator_label_y1 INTEGER NOT NULL DEFAULT -1,
                        locator_label_x2 INTEGER NOT NULL DEFAULT -1,
                        locator_label_y2 INTEGER NOT NULL DEFAULT -1,
                        header_crop_path TEXT NOT NULL DEFAULT '',
                        header_crop_sha256 TEXT NOT NULL DEFAULT '',
                        header_review_status TEXT NOT NULL DEFAULT 'pending',
                        header_target_field_key TEXT NOT NULL DEFAULT '',
                        header_exact_label TEXT NOT NULL DEFAULT '',
                        header_review_notes TEXT NOT NULL DEFAULT '',
                        header_reviewed_at TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        reviewed_at TEXT,
                        UNIQUE(source_id, field_key)
                    );
                    CREATE TABLE IF NOT EXISTS review_history (
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
                    CREATE TABLE IF NOT EXISTS detection_sources (
                        source_id TEXT PRIMARY KEY,
                        image_width INTEGER NOT NULL,
                        image_height INTEGER NOT NULL,
                        render_path TEXT NOT NULL,
                        detector_version TEXT NOT NULL,
                        token_count INTEGER NOT NULL DEFAULT 0,
                        block_count INTEGER NOT NULL DEFAULT 0,
                        relation_count INTEGER NOT NULL DEFAULT 0,
                        detected_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS detected_blocks (
                        block_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        block_type TEXT NOT NULL,
                        role TEXT NOT NULL,
                        text TEXT NOT NULL DEFAULT '',
                        normalized_text TEXT NOT NULL DEFAULT '',
                        confidence REAL NOT NULL DEFAULT 0,
                        x1 INTEGER NOT NULL,
                        y1 INTEGER NOT NULL,
                        x2 INTEGER NOT NULL,
                        y2 INTEGER NOT NULL,
                        line_index INTEGER NOT NULL DEFAULT 0,
                        sequence_index INTEGER NOT NULL DEFAULT 0,
                        parent_block_id TEXT NOT NULL DEFAULT '',
                        context_text TEXT NOT NULL DEFAULT '',
                        crop_path TEXT NOT NULL DEFAULT '',
                        table_id TEXT NOT NULL DEFAULT '',
                        row_index INTEGER NOT NULL DEFAULT -1,
                        column_index INTEGER NOT NULL DEFAULT -1,
                        row_span INTEGER NOT NULL DEFAULT 1,
                        column_span INTEGER NOT NULL DEFAULT 1,
                        geometry_source TEXT NOT NULL DEFAULT 'ocr',
                        recognition_text TEXT NOT NULL DEFAULT '',
                        recognition_confidence REAL NOT NULL DEFAULT 0,
                        recognition_model TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS detected_relations (
                        relation_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        label_block_id TEXT NOT NULL DEFAULT '',
                        value_block_id TEXT NOT NULL,
                        unit_block_id TEXT NOT NULL DEFAULT '',
                        relation_type TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0,
                        rank INTEGER NOT NULL DEFAULT 1,
                        context_text TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'proposed',
                        table_id TEXT NOT NULL DEFAULT '',
                        row_index INTEGER NOT NULL DEFAULT -1,
                        value_column_index INTEGER NOT NULL DEFAULT -1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS field_definitions (
                        field_key TEXT PRIMARY KEY,
                        display_name TEXT NOT NULL,
                        group_name TEXT NOT NULL DEFAULT '',
                        data_type TEXT NOT NULL DEFAULT 'text',
                        preferred_unit TEXT NOT NULL DEFAULT '',
                        aliases_json TEXT NOT NULL DEFAULT '[]',
                        minimum_value REAL,
                        maximum_value REAL,
                        required INTEGER NOT NULL DEFAULT 0,
                        active INTEGER NOT NULL DEFAULT 1,
                        built_in INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS field_mappings (
                        mapping_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        relation_id TEXT NOT NULL DEFAULT '',
                        field_key TEXT NOT NULL,
                        label_block_id TEXT NOT NULL DEFAULT '',
                        value_block_id TEXT NOT NULL,
                        unit_block_id TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'suggested',
                        mapping_confidence REAL NOT NULL DEFAULT 0,
                        notes TEXT NOT NULL DEFAULT '',
                        profile_id TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_id, field_key),
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE,
                        FOREIGN KEY(field_key) REFERENCES field_definitions(field_key)
                    );
                    CREATE TABLE IF NOT EXISTS mapping_profiles (
                        profile_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT NOT NULL DEFAULT '',
                        schema_version TEXT NOT NULL DEFAULT '1.0',
                        rules_json TEXT NOT NULL DEFAULT '[]',
                        source_id TEXT NOT NULL DEFAULT '',
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS detection_candidates (
                        candidate_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0,
                        source_kind TEXT NOT NULL DEFAULT 'text_geometry',
                        source_refs_json TEXT NOT NULL DEFAULT '[]',
                        crop_path TEXT NOT NULL DEFAULT '',
                        x1 INTEGER NOT NULL,
                        y1 INTEGER NOT NULL,
                        x2 INTEGER NOT NULL,
                        y2 INTEGER NOT NULL,
                        status TEXT NOT NULL DEFAULT 'proposed',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS detection_reviews (
                        review_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL DEFAULT '',
                        review_status TEXT NOT NULL,
                        reason_code TEXT NOT NULL DEFAULT '',
                        relevance_status TEXT NOT NULL DEFAULT 'relevant',
                        relevance_reason TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        original_x1 INTEGER NOT NULL,
                        original_y1 INTEGER NOT NULL,
                        original_x2 INTEGER NOT NULL,
                        original_y2 INTEGER NOT NULL,
                        corrected_x1 INTEGER NOT NULL,
                        corrected_y1 INTEGER NOT NULL,
                        corrected_x2 INTEGER NOT NULL,
                        corrected_y2 INTEGER NOT NULL,
                        reviewed_at TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS detection_annotations (
                        annotation_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL DEFAULT '',
                        review_id TEXT NOT NULL DEFAULT '',
                        provenance TEXT NOT NULL,
                        training_role TEXT NOT NULL DEFAULT 'positive',
                        x1 INTEGER NOT NULL,
                        y1 INTEGER NOT NULL,
                        x2 INTEGER NOT NULL,
                        y2 INTEGER NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS detection_table_regions (
                        table_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        confidence REAL NOT NULL DEFAULT 0,
                        x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, x2 INTEGER NOT NULL, y2 INTEGER NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS detection_table_cells (
                        cell_id TEXT PRIMARY KEY,
                        table_id TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        row_index INTEGER NOT NULL DEFAULT -1,
                        column_index INTEGER NOT NULL DEFAULT -1,
                        confidence REAL NOT NULL DEFAULT 0,
                        x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, x2 INTEGER NOT NULL, y2 INTEGER NOT NULL,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        FOREIGN KEY(source_id) REFERENCES detection_sources(source_id) ON DELETE CASCADE,
                        FOREIGN KEY(table_id) REFERENCES detection_table_regions(table_id) ON DELETE CASCADE
                    );
                    CREATE TABLE IF NOT EXISTS localization_datasets (
                        dataset_id TEXT PRIMARY KEY,
                        path TEXT NOT NULL,
                        image_count INTEGER NOT NULL DEFAULT 0,
                        annotation_count INTEGER NOT NULL DEFAULT 0,
                        negative_image_count INTEGER NOT NULL DEFAULT 0,
                        split_json TEXT NOT NULL DEFAULT '{}',
                        manifest_json TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS localization_models (
                        model_id TEXT PRIMARY KEY,
                        model_name TEXT NOT NULL,
                        path TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'registered',
                        device TEXT NOT NULL DEFAULT '',
                        dataset_id TEXT NOT NULL DEFAULT '',
                        metrics_json TEXT NOT NULL DEFAULT '{}',
                        active INTEGER NOT NULL DEFAULT 0,
                        registered_at TEXT NOT NULL,
                        activated_at TEXT
                    );
                    CREATE TABLE IF NOT EXISTS localization_evaluations (
                        evaluation_id TEXT PRIMARY KEY,
                        model_id TEXT NOT NULL DEFAULT '',
                        dataset_id TEXT NOT NULL DEFAULT '',
                        kind TEXT NOT NULL DEFAULT 'baseline',
                        split TEXT NOT NULL DEFAULT 'test',
                        metrics_json TEXT NOT NULL DEFAULT '{}',
                        predictions_path TEXT NOT NULL DEFAULT '',
                        created_at TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS mapping_relation_feedback (
                        feedback_id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        relation_id TEXT NOT NULL DEFAULT '',
                        relation_signature TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        reason_code TEXT NOT NULL DEFAULT '',
                        reason_detail TEXT NOT NULL DEFAULT '',
                        snapshot_json TEXT NOT NULL DEFAULT '{}',
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(source_id, relation_signature)
                    );
                    """
                )
                self._ensure_columns(db)
                self._ensure_review_history_columns(db)
                self._ensure_detection_columns(db)
                db.executescript(
                    """
                    CREATE INDEX IF NOT EXISTS idx_samples_status ON samples(status);
                    CREATE INDEX IF NOT EXISTS idx_samples_source ON samples(source_id);
                    CREATE INDEX IF NOT EXISTS idx_samples_field ON samples(field_key);
                    CREATE INDEX IF NOT EXISTS idx_samples_confidence ON samples(raw_confidence);
                    CREATE INDEX IF NOT EXISTS idx_samples_method ON samples(extraction_method);
                    CREATE INDEX IF NOT EXISTS idx_samples_roi_review_status ON samples(roi_review_status);
                    CREATE INDEX IF NOT EXISTS idx_samples_header_review_status ON samples(header_review_status);
                    CREATE INDEX IF NOT EXISTS idx_detected_blocks_source ON detected_blocks(source_id);
                    CREATE INDEX IF NOT EXISTS idx_detected_blocks_role ON detected_blocks(role);
                    CREATE INDEX IF NOT EXISTS idx_detected_relations_source ON detected_relations(source_id);
                    CREATE INDEX IF NOT EXISTS idx_field_mappings_source ON field_mappings(source_id);
                    CREATE INDEX IF NOT EXISTS idx_field_mappings_status ON field_mappings(status);
                    CREATE INDEX IF NOT EXISTS idx_mapping_relation_feedback_source ON mapping_relation_feedback(source_id);
                    CREATE INDEX IF NOT EXISTS idx_mapping_relation_feedback_signature ON mapping_relation_feedback(relation_signature);
                    CREATE INDEX IF NOT EXISTS idx_mapping_relation_feedback_verdict ON mapping_relation_feedback(verdict, active);
                    CREATE INDEX IF NOT EXISTS idx_detection_candidates_source ON detection_candidates(source_id);
                    CREATE INDEX IF NOT EXISTS idx_detection_candidates_status ON detection_candidates(status);
                    CREATE INDEX IF NOT EXISTS idx_detection_reviews_source ON detection_reviews(source_id);
                    CREATE INDEX IF NOT EXISTS idx_detection_reviews_relevance ON detection_reviews(relevance_status, source_id);
                    CREATE INDEX IF NOT EXISTS idx_detection_annotations_source ON detection_annotations(source_id, active);
                    CREATE INDEX IF NOT EXISTS idx_detection_annotations_role ON detection_annotations(training_role, active, source_id);
                    CREATE INDEX IF NOT EXISTS idx_detection_table_cells_source ON detection_table_cells(source_id);
                    CREATE INDEX IF NOT EXISTS idx_localization_models_active ON localization_models(active);
                    CREATE INDEX IF NOT EXISTS idx_localization_evaluations_kind ON localization_evaluations(kind, created_at);
                    """
                )
                # Existing rows gain a sensible default target for the new row-header
                # normalization review without being silently marked as reviewed.
                db.execute(
                    "UPDATE samples SET header_target_field_key=field_key "
                    "WHERE TRIM(header_target_field_key)=''"
                )

                # v6 separates spatial ROI assessment from OCR value assessment.
                # Legacy value-review decisions marked as roi_error are moved to the
                # dedicated ROI state and reset to a pending value decision.
                migration_time = utc_now()
                db.execute(
                    """
                    INSERT INTO review_history(
                        sample_id, status, exact_label, notes, content_class,
                        crop_sha256, reviewed_at, invalidated_at, reason
                    )
                    SELECT sample_id, status, exact_label, notes, content_class,
                           crop_sha256, reviewed_at, ?, 'legacy_roi_error_moved_to_roi_review'
                    FROM samples
                    WHERE status='roi_error'
                    """,
                    (migration_time,),
                )
                db.execute(
                    """
                    UPDATE samples
                    SET roi_review_status='incorrect',
                        roi_review_notes=CASE
                            WHEN TRIM(roi_review_notes)='' THEN notes
                            ELSE roi_review_notes
                        END,
                        roi_reviewed_at=COALESCE(roi_reviewed_at, reviewed_at, ?),
                        status='pending', exact_label=NULL, notes='',
                        content_class='unknown', reviewed_at=NULL, updated_at=?
                    WHERE status='roi_error'
                    """,
                    (migration_time, migration_time),
                )
                db.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                    (str(SCHEMA_VERSION),),
                )
                db.execute(
                    "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_migrated_at', ?)",
                    (utc_now(),),
                )
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        finally:
            self._initializing = False

    @staticmethod
    def _invalidates_review(existing: sqlite3.Row, values: dict[str, Any]) -> tuple[bool, str]:
        old_hash = str(existing["crop_sha256"] or "")
        new_hash = str(values.get("crop_sha256") or "")
        if old_hash and new_hash and old_hash != new_hash:
            return True, "crop_pixels_changed"
        old_method = str(existing["extraction_method"] or "fixed_roi")
        new_method = str(values.get("extraction_method") or "fixed_roi")
        if old_method != new_method and existing["status"] != "pending":
            return True, f"extraction_method_changed:{old_method}->{new_method}"
        return False, ""

    def upsert_sample(self, sample: dict[str, Any]) -> bool:
        now = utc_now()
        values = {
            "extraction_method": "fixed_roi",
            "locator_confidence": 0.0,
            "locator_label_text": "",
            "locator_version": "",
            "locator_label_x1": -1,
            "locator_label_y1": -1,
            "locator_label_x2": -1,
            "locator_label_y2": -1,
            "header_crop_path": "",
            "header_crop_sha256": "",
            "crop_sha256": "",
            **sample,
            "created_at": sample.get("created_at", now),
            "updated_at": now,
        }
        values.setdefault("header_target_field_key", str(values.get("field_key") or ""))
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM samples WHERE sample_id=?", (values["sample_id"],)
            ).fetchone()
            if existing:
                invalidate, reason = self._invalidates_review(existing, values)
                invalidate_header_review = (
                    str(existing["locator_label_text"] or "")
                    != str(values.get("locator_label_text") or "")
                )
                if invalidate and (
                    existing["status"] != "pending" or existing["exact_label"] is not None
                ):
                    db.execute(
                        """
                        INSERT INTO review_history(
                            sample_id, status, exact_label, notes, content_class,
                            crop_sha256, reviewed_at, invalidated_at, reason
                        ) VALUES(?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            existing["sample_id"],
                            existing["status"],
                            existing["exact_label"],
                            existing["notes"],
                            existing["content_class"],
                            existing["crop_sha256"],
                            existing["reviewed_at"],
                            now,
                            reason,
                        ),
                    )
                db.execute(
                    """
                    UPDATE samples SET
                        crop_path=:crop_path,
                        raw_ocr=:raw_ocr,
                        raw_confidence=:raw_confidence,
                        raw_variant=:raw_variant,
                        image_width=:image_width,
                        image_height=:image_height,
                        roi_x1=:roi_x1, roi_y1=:roi_y1, roi_x2=:roi_x2, roi_y2=:roi_y2,
                        extraction_method=:extraction_method,
                        locator_confidence=:locator_confidence,
                        locator_label_text=:locator_label_text,
                        locator_version=:locator_version,
                        locator_label_x1=:locator_label_x1,
                        locator_label_y1=:locator_label_y1,
                        locator_label_x2=:locator_label_x2,
                        locator_label_y2=:locator_label_y2,
                        header_crop_path=:header_crop_path,
                        header_crop_sha256=:header_crop_sha256,
                        crop_sha256=:crop_sha256,
                        status=CASE WHEN :invalidate_review THEN 'pending' ELSE status END,
                        exact_label=CASE WHEN :invalidate_review THEN NULL ELSE exact_label END,
                        content_class=CASE WHEN :invalidate_review THEN 'unknown' ELSE content_class END,
                        notes=CASE WHEN :invalidate_review THEN '' ELSE notes END,
                        reviewed_at=CASE WHEN :invalidate_review THEN NULL ELSE reviewed_at END,
                        roi_review_status=CASE WHEN :invalidate_review THEN 'pending' ELSE roi_review_status END,
                        roi_review_notes=CASE WHEN :invalidate_review THEN '' ELSE roi_review_notes END,
                        roi_reviewed_at=CASE WHEN :invalidate_review THEN NULL ELSE roi_reviewed_at END,
                        review_generation=review_generation + CASE WHEN :invalidate_review THEN 1 ELSE 0 END,
                        header_review_status=CASE WHEN :invalidate_header_review THEN 'pending' ELSE header_review_status END,
                        header_target_field_key=CASE WHEN :invalidate_header_review THEN field_key ELSE header_target_field_key END,
                        header_exact_label=CASE WHEN :invalidate_header_review THEN '' ELSE header_exact_label END,
                        header_review_notes=CASE WHEN :invalidate_header_review THEN '' ELSE header_review_notes END,
                        header_reviewed_at=CASE WHEN :invalidate_header_review THEN NULL ELSE header_reviewed_at END,
                        updated_at=:updated_at
                    WHERE sample_id=:sample_id
                    """,
                    {**values, "invalidate_review": 1 if invalidate else 0, "invalidate_header_review": 1 if invalidate_header_review else 0},
                )
                return False
            db.execute(
                """
                INSERT INTO samples(
                    sample_id, source_id, profile, field_key, field_label, crop_path,
                    raw_ocr, raw_confidence, raw_variant, status, exact_label, notes,
                    image_width, image_height, roi_x1, roi_y1, roi_x2, roi_y2,
                    extraction_method, locator_confidence, locator_label_text,
                    locator_version, locator_label_x1, locator_label_y1,
                    locator_label_x2, locator_label_y2, header_crop_path,
                    header_crop_sha256, header_review_status, header_target_field_key,
                    header_exact_label, header_review_notes, header_reviewed_at,
                    crop_sha256, content_class, review_generation, created_at, updated_at
                ) VALUES(
                    :sample_id, :source_id, :profile, :field_key, :field_label, :crop_path,
                    :raw_ocr, :raw_confidence, :raw_variant, 'pending', NULL, '',
                    :image_width, :image_height, :roi_x1, :roi_y1, :roi_x2, :roi_y2,
                    :extraction_method, :locator_confidence, :locator_label_text,
                    :locator_version, :locator_label_x1, :locator_label_y1,
                    :locator_label_x2, :locator_label_y2, :header_crop_path,
                    :header_crop_sha256, 'pending', :header_target_field_key,
                    '', '', NULL, :crop_sha256, 'unknown', 0, :created_at, :updated_at
                )
                """,
                values,
            )
            return True

    def get(self, sample_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM samples WHERE sample_id=?", (sample_id,)).fetchone()
        return dict(row) if row else None

    def review(
        self,
        sample_id: str,
        status: str,
        exact_label: str | None,
        notes: str = "",
        content_class: str | None = None,
    ) -> None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Unsupported sample status: {status}")
        if content_class is None:
            content_class = "value" if status == "accepted" else "unknown"
        if content_class not in VALID_CONTENT_CLASSES:
            raise ValueError(f"Unsupported content class: {content_class}")
        if status == "accepted":
            if exact_label is None:
                raise ValueError("Accepted samples require an exact label")
            validate_exact_label(exact_label)
            if content_class not in {"value", "placeholder"}:
                raise ValueError("Accepted samples must be a value or placeholder")
        else:
            exact_label = None
            if status == "no_value":
                content_class = "no_value"
            elif content_class != "no_value":
                content_class = "unknown"
        now = utc_now()
        with self.connect() as db:
            changed = db.execute(
                """
                UPDATE samples SET status=?, exact_label=?, notes=?, content_class=?,
                    reviewed_at=?, updated_at=?
                WHERE sample_id=?
                """,
                (status, exact_label, notes, content_class, now, now, sample_id),
            ).rowcount
            if not changed:
                raise KeyError(sample_id)


    def review_header(
        self,
        sample_id: str,
        status: str,
        target_field_key: str | None = None,
        exact_label: str = "",
        notes: str = "",
    ) -> None:
        if status not in VALID_HEADER_REVIEW_STATUSES:
            raise ValueError(f"Unsupported header review status: {status}")
        exact_label = validate_exact_label(str(exact_label or ""))
        target = str(target_field_key or "").strip()
        now = utc_now()
        reviewed_at = None if status == "pending" else now
        with self.connect() as db:
            existing = db.execute(
                "SELECT field_key, locator_label_text FROM samples WHERE sample_id=?",
                (sample_id,),
            ).fetchone()
            if existing is None:
                raise KeyError(sample_id)
            if status == "accepted":
                if not str(existing["locator_label_text"] or "").strip():
                    raise ValueError("A header without OCR text cannot be used for normalization training")
                if not target:
                    raise ValueError("Accepted header reviews require a target field")
            elif not target:
                target = str(existing["field_key"] or "")
            db.execute(
                """
                UPDATE samples SET header_review_status=?, header_target_field_key=?,
                    header_exact_label=?, header_review_notes=?, header_reviewed_at=?,
                    updated_at=?
                WHERE sample_id=?
                """,
                (status, target, exact_label, notes, reviewed_at, now, sample_id),
            )

    def header_review_counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT header_review_status, COUNT(*) AS amount FROM samples "
                "WHERE TRIM(locator_label_text)<>'' GROUP BY header_review_status"
            ).fetchall()
        counts = {status: 0 for status in VALID_HEADER_REVIEW_STATUSES}
        for row in rows:
            status = str(row["header_review_status"] or "pending")
            if status in counts:
                counts[status] = int(row["amount"])
        counts["total"] = sum(counts.values())
        return counts

    def list_header_samples(
        self,
        status: str | None = None,
        *,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["TRIM(locator_label_text)<>''"]
        params: list[Any] = []
        if status and status != "all":
            if status not in VALID_HEADER_REVIEW_STATUSES:
                raise ValueError(f"Unsupported header review status: {status}")
            clauses.append("header_review_status=?")
            params.append(status)
        params.extend([limit, offset])
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT * FROM samples
                WHERE {' AND '.join(clauses)}
                ORDER BY CASE header_review_status
                           WHEN 'pending' THEN 0 WHEN 'deferred' THEN 1
                           WHEN 'rejected' THEN 2 ELSE 3 END,
                         locator_confidence ASC, source_id, roi_y1, field_key
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def header_training_rows(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT sample_id, field_key, locator_label_text,
                       header_review_status, header_target_field_key, header_exact_label
                FROM samples
                WHERE header_review_status='accepted'
                ORDER BY source_id, field_key
                """
            ).fetchall()
        return [dict(row) for row in rows]


    def review_roi(self, sample_id: str, status: str, notes: str = "") -> None:
        if status not in {"pending", "correct", "incorrect", "deferred"}:
            raise ValueError(f"Unsupported ROI review status: {status}")
        now = utc_now()
        reviewed_at = None if status == "pending" else now
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM samples WHERE sample_id=?", (sample_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(sample_id)

            # A value decision is only valid while the spatial crop is approved.
            # Moving a ROI back to pending or marking it incorrect therefore
            # invalidates the value decision without losing its audit history.
            invalidate_value = status != "correct" and (
                existing["status"] != "pending" or existing["exact_label"] is not None
            )
            if invalidate_value:
                db.execute(
                    """
                    INSERT INTO review_history(
                        sample_id, status, exact_label, notes, content_class,
                        crop_sha256, reviewed_at, invalidated_at, reason
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        existing["sample_id"], existing["status"], existing["exact_label"],
                        existing["notes"], existing["content_class"], existing["crop_sha256"],
                        existing["reviewed_at"], now, f"roi_review_changed_to_{status}",
                    ),
                )
            db.execute(
                """
                UPDATE samples SET roi_review_status=?, roi_review_notes=?,
                    roi_reviewed_at=?,
                    status=CASE WHEN ? THEN 'pending' ELSE status END,
                    exact_label=CASE WHEN ? THEN NULL ELSE exact_label END,
                    notes=CASE WHEN ? THEN '' ELSE notes END,
                    content_class=CASE WHEN ? THEN 'unknown' ELSE content_class END,
                    reviewed_at=CASE WHEN ? THEN NULL ELSE reviewed_at END,
                    review_generation=review_generation + CASE WHEN ? THEN 1 ELSE 0 END,
                    updated_at=?
                WHERE sample_id=?
                """,
                (
                    status, notes, reviewed_at,
                    invalidate_value, invalidate_value, invalidate_value, invalidate_value,
                    invalidate_value, invalidate_value, now, sample_id,
                ),
            )

    def list_samples(
        self,
        status: str | None = None,
        field_key: str | None = None,
        min_confidence: float | None = None,
        max_confidence: float | None = None,
        ocr_content: str = "all",
        extraction_method: str | None = None,
        roi_review_status: str | None = None,
        exclude_sample_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if ocr_content not in VALID_OCR_CONTENT_FILTERS:
            raise ValueError(f"Unsupported OCR content filter: {ocr_content}")
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if field_key:
            clauses.append("field_key=?")
            params.append(field_key)
        if min_confidence is not None:
            clauses.append("raw_confidence>=?")
            params.append(float(min_confidence))
        if max_confidence is not None:
            clauses.append("raw_confidence<?")
            params.append(float(max_confidence))
        if extraction_method:
            clauses.append("extraction_method=?")
            params.append(extraction_method)
        if roi_review_status:
            if roi_review_status not in {"pending", "correct", "incorrect", "deferred"}:
                raise ValueError(f"Unsupported ROI review status: {roi_review_status}")
            clauses.append("roi_review_status=?")
            params.append(roi_review_status)
        if exclude_sample_id:
            clauses.append("sample_id<>?")
            params.append(exclude_sample_id)

        trimmed = "TRIM(raw_ocr)"
        marker_placeholders = ",".join("?" for _ in MISSING_MARKERS)
        if ocr_content == "text":
            clauses.append(f"{trimmed}<>'' AND {trimmed} NOT IN ({marker_placeholders})")
            params.extend(MISSING_MARKERS)
        elif ocr_content == "blank":
            clauses.append(f"{trimmed}=''")
        elif ocr_content == "missing":
            clauses.append(f"{trimmed} IN ({marker_placeholders})")
            params.extend(MISSING_MARKERS)
        elif ocr_content == "blank_or_missing":
            clauses.append(f"({trimmed}='' OR {trimmed} IN ({marker_placeholders}))")
            params.extend(MISSING_MARKERS)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        query = f"""
            SELECT * FROM samples {where}
            ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                     CASE extraction_method WHEN 'fixed_fallback' THEN 0 ELSE 1 END,
                     raw_confidence ASC, field_key, sample_id
            LIMIT ? OFFSET ?
        """
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def accepted(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM samples WHERE status='accepted' AND exact_label IS NOT NULL "
                "AND roi_review_status='correct' ORDER BY source_id, field_key"
            ).fetchall()
        return [dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS count FROM samples GROUP BY status"
            ).fetchall()
            total = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            classes = db.execute(
                "SELECT content_class, COUNT(*) AS count FROM samples GROUP BY content_class"
            ).fetchall()
        result = {status: 0 for status in VALID_STATUSES}
        result.update({row["status"]: int(row["count"]) for row in rows})
        result["total"] = int(total)
        for row in classes:
            result[f"class_{row['content_class']}"] = int(row["count"])
        return result

    def mapped_sample_counts(self) -> dict[str, int]:
        """Aggregate mapped-sample state in SQLite instead of loading all rows."""
        with self.connect() as db:
            row = db.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN raw_variant='awaiting_value_recognition' THEN 1 ELSE 0 END) AS awaiting_recognition,
                    SUM(CASE WHEN raw_variant<>'awaiting_value_recognition' THEN 1 ELSE 0 END) AS recognized,
                    SUM(CASE WHEN roi_review_status='correct' THEN 1 ELSE 0 END) AS roi_correct
                FROM samples
                WHERE extraction_method='mapped_generic'
                """
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "awaiting_recognition": int(row["awaiting_recognition"] or 0),
            "recognized": int(row["recognized"] or 0),
            "roi_correct": int(row["roi_correct"] or 0),
        }

    def fields(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT field_key, field_label, COUNT(*) AS count,
                       SUM(CASE WHEN status='accepted' THEN 1 ELSE 0 END) AS accepted
                FROM samples WHERE roi_review_status='correct'
                GROUP BY field_key, field_label ORDER BY field_key
                """
            ).fetchall()
        return [dict(row) for row in rows]


    # ------------------------------------------------------------------
    # Generic detection, schema and mapping storage (schema v8+, table metadata in v9)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_field_key(value: str) -> str:
        key = re.sub(r"[^a-z0-9_.-]+", "_", str(value or "").strip().casefold()).strip("_.-")
        if not key:
            raise ValueError("Field key cannot be empty")
        if len(key) > 160:
            raise ValueError("Field key is too long")
        return key

    def seed_field_definitions(self, definitions: list[dict[str, Any]]) -> int:
        """Insert built-in field definitions without overwriting user edits."""
        now = utc_now()
        inserted = 0
        with self.connect() as db:
            for item in definitions:
                key = self._safe_field_key(str(item.get("field_key") or item.get("key") or ""))
                aliases = [str(value).strip() for value in item.get("aliases", []) if str(value).strip()]
                data_type = str(item.get("data_type") or "text").strip().lower()
                if data_type not in VALID_FIELD_TYPES:
                    data_type = "text"
                result = db.execute(
                    """
                    INSERT OR IGNORE INTO field_definitions(
                        field_key, display_name, group_name, data_type, preferred_unit,
                        aliases_json, minimum_value, maximum_value, required, active,
                        built_in, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        key,
                        str(item.get("display_name") or item.get("label") or key),
                        str(item.get("group_name") or item.get("group") or ""),
                        data_type,
                        str(item.get("preferred_unit") or item.get("unit") or ""),
                        json.dumps(aliases, ensure_ascii=False),
                        item.get("minimum_value"),
                        item.get("maximum_value"),
                        1 if item.get("required") else 0,
                        1,
                        1 if item.get("built_in", True) else 0,
                        now,
                        now,
                    ),
                )
                inserted += int(result.rowcount > 0)
        return inserted

    def upsert_field_definition(
        self,
        field_key: str,
        display_name: str,
        *,
        group_name: str = "",
        data_type: str = "text",
        preferred_unit: str = "",
        aliases: list[str] | None = None,
        minimum_value: float | None = None,
        maximum_value: float | None = None,
        required: bool = False,
        active: bool = True,
        built_in: bool = False,
    ) -> dict[str, Any]:
        key = self._safe_field_key(field_key)
        name = str(display_name or "").strip()
        if not name:
            raise ValueError("Display name cannot be empty")
        data_type = str(data_type or "text").strip().lower()
        if data_type not in VALID_FIELD_TYPES:
            raise ValueError(f"Unsupported field type: {data_type}")
        aliases = [str(value).strip() for value in (aliases or []) if str(value).strip()]
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO field_definitions(
                    field_key, display_name, group_name, data_type, preferred_unit,
                    aliases_json, minimum_value, maximum_value, required, active,
                    built_in, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(field_key) DO UPDATE SET
                    display_name=excluded.display_name,
                    group_name=excluded.group_name,
                    data_type=excluded.data_type,
                    preferred_unit=excluded.preferred_unit,
                    aliases_json=excluded.aliases_json,
                    minimum_value=excluded.minimum_value,
                    maximum_value=excluded.maximum_value,
                    required=excluded.required,
                    active=excluded.active,
                    built_in=CASE WHEN field_definitions.built_in=1 THEN 1 ELSE excluded.built_in END,
                    updated_at=excluded.updated_at
                """,
                (
                    key, name, str(group_name or ""), data_type, str(preferred_unit or ""),
                    json.dumps(aliases, ensure_ascii=False), minimum_value, maximum_value,
                    1 if required else 0, 1 if active else 0, 1 if built_in else 0,
                    now, now,
                ),
            )
        result = self.get_field_definition(key)
        if result is None:
            raise RuntimeError("Field definition was not stored")
        return result

    def set_field_active(self, field_key: str, active: bool) -> None:
        with self.connect() as db:
            changed = db.execute(
                "UPDATE field_definitions SET active=?, updated_at=? WHERE field_key=?",
                (1 if active else 0, utc_now(), field_key),
            ).rowcount
            if not changed:
                raise KeyError(field_key)

    def get_field_definition(self, field_key: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM field_definitions WHERE field_key=?", (field_key,)
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
        except (TypeError, ValueError):
            item["aliases"] = []
        return item

    def list_field_definitions(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM field_definitions {where} ORDER BY group_name, display_name, field_key"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["aliases"] = json.loads(item.pop("aliases_json") or "[]")
            except (TypeError, ValueError):
                item["aliases"] = []
            result.append(item)
        return result

    @staticmethod
    def _invalidate_mapped_samples_in_connection(
        db: sqlite3.Connection,
        source_id: str,
        field_keys: list[str] | tuple[str, ...] | set[str],
        *,
        reason: str,
    ) -> int:
        """Retire ROI/value reviews that were created from a mapping that changed.

        A mapped crop must never remain eligible for recognition or dataset export
        after its semantic mapping or source geometry changes. The old crop is kept
        for diagnostics, but the sample is marked stale until action 21 materializes
        the current confirmed mapping again.
        """
        keys = sorted({str(key) for key in field_keys if str(key)})
        if not keys:
            return 0
        placeholders = ",".join("?" for _ in keys)
        rows = db.execute(
            f"SELECT * FROM samples WHERE source_id=? AND field_key IN ({placeholders}) AND extraction_method='mapped_generic'",
            [source_id, *keys],
        ).fetchall()
        if not rows:
            return 0
        now = utc_now()
        for existing in rows:
            if existing["status"] != "pending" or existing["exact_label"] is not None:
                db.execute(
                    """
                    INSERT INTO review_history(
                        sample_id, status, exact_label, notes, content_class,
                        crop_sha256, reviewed_at, invalidated_at, reason
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        existing["sample_id"], existing["status"], existing["exact_label"],
                        existing["notes"], existing["content_class"], existing["crop_sha256"],
                        existing["reviewed_at"], now, reason,
                    ),
                )
        db.execute(
            f"""
            UPDATE samples SET
                extraction_method='mapped_generic_stale',
                raw_ocr='', raw_confidence=0, raw_variant='mapping_changed',
                status='pending', exact_label=NULL, notes='', content_class='unknown', reviewed_at=NULL,
                roi_review_status='pending', roi_review_notes=?, roi_reviewed_at=NULL,
                review_generation=review_generation+1, updated_at=?
            WHERE source_id=? AND field_key IN ({placeholders}) AND extraction_method='mapped_generic'
            """,
            [f"Opnieuw materialiseren vereist: {reason}", now, source_id, *keys],
        )
        return len(rows)

    def invalidate_mapped_samples(
        self, source_id: str, field_keys: list[str] | tuple[str, ...] | set[str], *, reason: str
    ) -> int:
        with self.connect() as db:
            return self._invalidate_mapped_samples_in_connection(
                db, source_id, field_keys, reason=reason
            )

    def replace_generic_detection(
        self,
        source: dict[str, Any],
        blocks: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> None:
        source_id = str(source["source_id"])
        now = utc_now()
        with self.connect() as db:
            # Preserve confirmed mappings only when the exact referenced block IDs
            # still exist. A mapping to deleted geometry is not a valid suggestion:
            # retire its ROI and remove the orphan mapping so fresh suggestions can
            # be computed against the new detection graph.
            confirmed = db.execute(
                "SELECT * FROM field_mappings WHERE source_id=? AND status='confirmed'",
                (source_id,),
            ).fetchall()
            # Suggestions depend on the current detection geometry. Recreate them
            # after every detection run instead of retaining references to stale
            # blocks or relations. Confirmed mappings are handled separately.
            db.execute(
                "DELETE FROM field_mappings WHERE source_id=? AND status<>'confirmed'",
                (source_id,),
            )
            db.execute("DELETE FROM detected_relations WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detected_blocks WHERE source_id=?", (source_id,))
            db.execute(
                """
                INSERT INTO detection_sources(
                    source_id, image_width, image_height, render_path, detector_version,
                    token_count, block_count, relation_count, detected_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    image_width=excluded.image_width,
                    image_height=excluded.image_height,
                    render_path=excluded.render_path,
                    detector_version=excluded.detector_version,
                    token_count=excluded.token_count,
                    block_count=excluded.block_count,
                    relation_count=excluded.relation_count,
                    detected_at=excluded.detected_at,
                    updated_at=excluded.updated_at
                """,
                (
                    source_id, int(source["image_width"]), int(source["image_height"]),
                    str(source.get("render_path") or ""), str(source.get("detector_version") or ""),
                    int(source.get("token_count") or 0), len(blocks), len(relations), now, now,
                ),
            )
            for block in blocks:
                db.execute(
                    """
                    INSERT INTO detected_blocks(
                        block_id, source_id, block_type, role, text, normalized_text,
                        confidence, x1, y1, x2, y2, line_index, sequence_index,
                        parent_block_id, context_text, crop_path, table_id, row_index,
                        column_index, row_span, column_span, geometry_source,
                        recognition_text, recognition_confidence, recognition_model,
                        created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        block["block_id"], source_id, block["block_type"], block["role"],
                        block.get("text", ""), block.get("normalized_text", ""),
                        float(block.get("confidence") or 0), int(block["x1"]), int(block["y1"]),
                        int(block["x2"]), int(block["y2"]), int(block.get("line_index") or 0),
                        int(block.get("sequence_index") or 0), str(block.get("parent_block_id") or ""),
                        str(block.get("context_text") or ""), str(block.get("crop_path") or ""),
                        str(block.get("table_id") or ""), int(block.get("row_index", -1)),
                        int(block.get("column_index", -1)), int(block.get("row_span") or 1),
                        int(block.get("column_span") or 1), str(block.get("geometry_source") or "ocr"),
                        str(block.get("recognition_text") or ""),
                        float(block.get("recognition_confidence") or 0),
                        str(block.get("recognition_model") or ""),
                        now, now,
                    ),
                )
            for relation in relations:
                db.execute(
                    """
                    INSERT INTO detected_relations(
                        relation_id, source_id, label_block_id, value_block_id,
                        unit_block_id, relation_type, confidence, rank, context_text,
                        status, table_id, row_index, value_column_index, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,'proposed',?,?,?,?,?)
                    """,
                    (
                        relation["relation_id"], source_id, str(relation.get("label_block_id") or ""),
                        relation["value_block_id"], str(relation.get("unit_block_id") or ""),
                        relation.get("relation_type", "same_line_right"),
                        float(relation.get("confidence") or 0), int(relation.get("rank") or 1),
                        str(relation.get("context_text") or ""), str(relation.get("table_id") or ""),
                        int(relation.get("row_index", -1)), int(relation.get("value_column_index", -1)),
                        now, now,
                    ),
                )
            # Re-apply feedback after a new detection pass. Relation IDs can move
            # when OCR geometry changes, therefore the durable feedback key is a
            # normalized text/value/geometry signature rather than relation_id.
            prior_feedback = {
                str(row["relation_signature"]): str(row["verdict"])
                for row in db.execute(
                    "SELECT relation_signature, verdict FROM mapping_relation_feedback WHERE source_id=? AND active=1",
                    (source_id,),
                ).fetchall()
            }
            for relation in relations:
                relation_id = str(relation["relation_id"])
                snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
                if snapshot is None:
                    continue
                verdict = prior_feedback.get(relation_signature(snapshot))
                if verdict in {"accepted", "rejected"}:
                    db.execute(
                        "UPDATE detected_relations SET status=?, updated_at=? WHERE relation_id=?",
                        (verdict, now, relation_id),
                    )

            valid_block_ids = {str(item["block_id"]) for item in blocks}
            valid_relation_ids = {str(item["relation_id"]) for item in relations}
            for mapping in confirmed:
                if (
                    str(mapping["value_block_id"]) not in valid_block_ids
                    or (str(mapping["label_block_id"] or "") and str(mapping["label_block_id"]) not in valid_block_ids)
                    or (str(mapping["relation_id"] or "") and str(mapping["relation_id"]) not in valid_relation_ids)
                ):
                    self._invalidate_mapped_samples_in_connection(
                        db, source_id, [str(mapping["field_key"])], reason="detection_changed"
                    )
                    db.execute(
                        "DELETE FROM field_mappings WHERE mapping_id=?",
                        (mapping["mapping_id"],),
                    )

    def list_detection_sources(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT s.*,
                       SUM(CASE WHEN m.status='confirmed' THEN 1 ELSE 0 END) AS confirmed_mapping_count,
                       SUM(CASE WHEN m.status='suggested' THEN 1 ELSE 0 END) AS suggested_mapping_count
                FROM detection_sources s
                LEFT JOIN field_mappings m ON m.source_id=s.source_id
                GROUP BY s.source_id
                ORDER BY s.detected_at DESC, s.source_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_detection_source(self, source_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detection_sources WHERE source_id=?", (source_id,)).fetchone()
        return dict(row) if row else None

    def list_detected_blocks(
        self,
        source_id: str,
        *,
        role: str | None = None,
        semantic_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = ["source_id=?"]
        params: list[Any] = [source_id]
        if role and role != "all":
            clauses.append("role=?")
            params.append(role)
        if semantic_only:
            clauses.append("block_type IN ('semantic','table_cell')")
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM detected_blocks WHERE {' AND '.join(clauses)} ORDER BY y1, x1, line_index, sequence_index",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def get_detected_block(self, block_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detected_blocks WHERE block_id=?", (block_id,)).fetchone()
        return dict(row) if row else None

    def get_detected_relation(self, relation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM detected_relations WHERE relation_id=?", (relation_id,)
            ).fetchone()
        return dict(row) if row else None

    def _relation_snapshot_in_connection(
        self, db: sqlite3.Connection, source_id: str, relation_id: str
    ) -> dict[str, Any] | None:
        row = db.execute(
            """
            SELECT r.*,
                   s.image_width, s.image_height,
                   lb.text AS label_text, lb.x1 AS label_x1, lb.y1 AS label_y1,
                   lb.x2 AS label_x2, lb.y2 AS label_y2,
                   vb.text AS value_text, vb.x1 AS value_x1, vb.y1 AS value_y1,
                   vb.x2 AS value_x2, vb.y2 AS value_y2
            FROM detected_relations r
            JOIN detection_sources s ON s.source_id=r.source_id
            LEFT JOIN detected_blocks lb ON lb.block_id=r.label_block_id
            JOIN detected_blocks vb ON vb.block_id=r.value_block_id
            WHERE r.source_id=? AND r.relation_id=?
            """,
            (source_id, relation_id),
        ).fetchone()
        if row is None:
            return None
        payload = dict(row)
        source = {
            "source_id": source_id,
            "image_width": int(row["image_width"] or 1),
            "image_height": int(row["image_height"] or 1),
        }
        return relation_snapshot(payload, source)

    def _record_relation_feedback_in_connection(
        self,
        db: sqlite3.Connection,
        *,
        source_id: str,
        relation_id: str,
        verdict: str,
        reason_code: str = "",
        reason_detail: str = "",
    ) -> dict[str, Any]:
        verdict = str(verdict or "").strip().lower()
        reason_code = str(reason_code or "").strip().lower()
        if verdict not in VALID_RELATION_FEEDBACK_VERDICTS:
            raise ValueError(f"Unsupported relation feedback verdict: {verdict}")
        if verdict == "rejected" and reason_code not in RELATION_FEEDBACK_REASONS:
            raise ValueError("Choose a valid rejection reason")
        if verdict == "accepted":
            reason_code = ""
            reason_detail = ""

        snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
        if snapshot is None:
            raise ValueError("Relation does not belong to the selected source")
        signature = relation_signature(snapshot)
        feedback_id = hashlib.sha256(f"{source_id}|{signature}".encode("utf-8")).hexdigest()[:32]
        now = utc_now()
        db.execute(
            """
            INSERT INTO mapping_relation_feedback(
                feedback_id, source_id, relation_id, relation_signature, verdict,
                reason_code, reason_detail, snapshot_json, active, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,1,?,?)
            ON CONFLICT(source_id, relation_signature) DO UPDATE SET
                feedback_id=excluded.feedback_id,
                relation_id=excluded.relation_id,
                verdict=excluded.verdict,
                reason_code=excluded.reason_code,
                reason_detail=excluded.reason_detail,
                snapshot_json=excluded.snapshot_json,
                active=1,
                updated_at=excluded.updated_at
            """,
            (
                feedback_id, source_id, relation_id, signature, verdict,
                reason_code, str(reason_detail or "").strip(),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now, now,
            ),
        )
        db.execute(
            "UPDATE detected_relations SET status=?, updated_at=? WHERE source_id=? AND relation_id=?",
            ("rejected" if verdict == "rejected" else "accepted", now, source_id, relation_id),
        )
        return {
            "feedback_id": feedback_id,
            "source_id": source_id,
            "relation_id": relation_id,
            "relation_signature": signature,
            "verdict": verdict,
            "reason_code": reason_code,
            "reason_detail": str(reason_detail or "").strip(),
            "snapshot": snapshot,
            "active": 1,
        }

    def record_relation_feedback(
        self,
        *,
        source_id: str,
        relation_id: str,
        verdict: str,
        reason_code: str = "",
        reason_detail: str = "",
    ) -> dict[str, Any]:
        with self.connect() as db:
            if str(verdict).strip().lower() == "rejected":
                mappings = db.execute(
                    "SELECT * FROM field_mappings WHERE source_id=? AND relation_id=?",
                    (source_id, relation_id),
                ).fetchall()
                for mapping in mappings:
                    self._invalidate_mapped_samples_in_connection(
                        db, source_id, [str(mapping["field_key"])], reason="relation_rejected"
                    )
                    db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (mapping["mapping_id"],))
            return self._record_relation_feedback_in_connection(
                db,
                source_id=source_id,
                relation_id=relation_id,
                verdict=verdict,
                reason_code=reason_code,
                reason_detail=reason_detail,
            )

    def clear_relation_feedback(self, source_id: str, relation_id: str) -> int:
        with self.connect() as db:
            snapshot = self._relation_snapshot_in_connection(db, source_id, relation_id)
            if snapshot is None:
                raise ValueError("Relation does not belong to the selected source")
            signature = relation_signature(snapshot)
            result = db.execute(
                "DELETE FROM mapping_relation_feedback WHERE source_id=? AND relation_signature=?",
                (source_id, signature),
            )
            db.execute(
                "UPDATE detected_relations SET status='proposed', updated_at=? WHERE source_id=? AND relation_id=?",
                (utc_now(), source_id, relation_id),
            )
            return int(result.rowcount if result.rowcount is not None else 0)

    def list_relation_feedback(self, *, active_only: bool = True) -> list[dict[str, Any]]:
        where = "WHERE active=1" if active_only else ""
        with self.connect() as db:
            rows = db.execute(
                f"SELECT * FROM mapping_relation_feedback {where} ORDER BY updated_at DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["snapshot"] = json.loads(str(item.pop("snapshot_json") or "{}"))
            except json.JSONDecodeError:
                item["snapshot"] = {}
            result.append(item)
        return result

    def relation_feedback_stats(self) -> dict[str, Any]:
        with self.connect() as db:
            verdict_rows = db.execute(
                "SELECT verdict, COUNT(*) AS amount FROM mapping_relation_feedback WHERE active=1 GROUP BY verdict"
            ).fetchall()
            reason_rows = db.execute(
                """
                SELECT reason_code, COUNT(*) AS amount
                FROM mapping_relation_feedback
                WHERE active=1 AND verdict='rejected'
                GROUP BY reason_code ORDER BY amount DESC, reason_code
                """
            ).fetchall()
        stats: dict[str, Any] = {"accepted": 0, "rejected": 0, "total": 0, "reasons": {}}
        for row in verdict_rows:
            verdict = str(row["verdict"])
            if verdict in {"accepted", "rejected"}:
                stats[verdict] = int(row["amount"])
        stats["total"] = int(stats["accepted"]) + int(stats["rejected"])
        stats["reasons"] = {str(row["reason_code"]): int(row["amount"]) for row in reason_rows}
        return stats

    def feedback_for_relations(self, source_id: str, relations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        examples = [item for item in self.list_relation_feedback() if str(item.get("source_id") or "") == source_id]
        if not examples:
            return {}
        source = self.get_detection_source(source_id) or {"source_id": source_id}
        by_signature = {str(item.get("relation_signature") or ""): item for item in examples}
        result: dict[str, dict[str, Any]] = {}
        for relation in relations:
            snapshot = relation_snapshot(relation, source)
            item = by_signature.get(relation_signature(snapshot))
            if item is not None:
                result[str(relation["relation_id"])] = item
        return result

    def list_detected_relations(self, source_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT r.*,
                       lb.text AS label_text, lb.normalized_text AS label_normalized,
                       lb.crop_path AS label_crop_path, lb.x1 AS label_x1, lb.y1 AS label_y1,
                       lb.x2 AS label_x2, lb.y2 AS label_y2,
                       COALESCE(NULLIF(vb.recognition_text,''), vb.text) AS value_text,
                       vb.text AS value_locator_text,
                       vb.recognition_text AS value_recognition_text,
                       vb.recognition_confidence AS value_recognition_confidence,
                       vb.recognition_model AS value_recognition_model,
                       vb.normalized_text AS value_normalized,
                       vb.crop_path AS value_crop_path, vb.confidence AS value_confidence,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       ub.text AS unit_text, ub.crop_path AS unit_crop_path,
                       fm.mapping_id, fm.field_key AS mapped_field_key,
                       fm.status AS mapping_status, fm.mapping_confidence, fm.notes AS mapping_notes
                FROM detected_relations r
                LEFT JOIN detected_blocks lb ON lb.block_id=r.label_block_id
                JOIN detected_blocks vb ON vb.block_id=r.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=r.unit_block_id
                LEFT JOIN field_mappings fm ON fm.source_id=r.source_id AND fm.relation_id=r.relation_id
                WHERE r.source_id=?
                ORDER BY CASE WHEN r.relation_type='table_cell' THEN 0 ELSE 1 END,
                         COALESCE(NULLIF(r.table_id,''), r.source_id), r.row_index,
                         vb.y1, vb.x1, r.rank, r.confidence DESC
                """,
                (source_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def update_relation_contexts(
        self, source_id: str, contexts_by_relation: dict[str, str]
    ) -> int:
        """Persist refreshed table/panel context without rerunning detection."""
        if not contexts_by_relation:
            return 0
        updated = 0
        with self.connect() as db:
            for relation_id, context_text in contexts_by_relation.items():
                result = db.execute(
                    """UPDATE detected_relations
                       SET context_text=?, updated_at=?
                       WHERE source_id=? AND relation_id=?""",
                    (str(context_text or ""), utc_now(), source_id, relation_id),
                )
                updated += int(result.rowcount or 0)
        return updated

    def mapping_counts(self) -> dict[str, int]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS amount FROM field_mappings GROUP BY status"
            ).fetchall()
            relation_total = int(db.execute("SELECT COUNT(*) FROM detected_relations").fetchone()[0])
            source_total = int(db.execute("SELECT COUNT(*) FROM detection_sources").fetchone()[0])
        result = {status: 0 for status in VALID_MAPPING_STATUSES}
        for row in rows:
            if row["status"] in result:
                result[str(row["status"])] = int(row["amount"])
        result["relations"] = relation_total
        result["sources"] = source_total
        result["total"] = sum(result[status] for status in VALID_MAPPING_STATUSES)
        return result

    @staticmethod
    def _mapping_component_in_source(
        db: sqlite3.Connection, table: str, key_name: str, key_value: str, source_id: str
    ) -> sqlite3.Row | None:
        return db.execute(
            f"SELECT * FROM {table} WHERE {key_name}=? AND source_id=?",
            (key_value, source_id),
        ).fetchone()

    def _upsert_mapping_in_connection(
        self,
        db: sqlite3.Connection,
        *,
        source_id: str,
        field_key: str,
        value_block_id: str,
        label_block_id: str = "",
        unit_block_id: str = "",
        relation_id: str = "",
        status: str = "confirmed",
        mapping_confidence: float = 1.0,
        notes: str = "",
        profile_id: str = "",
    ) -> str:
        """Validate and store one mapping inside an existing transaction."""
        if status not in VALID_MAPPING_STATUSES:
            raise ValueError(f"Unsupported mapping status: {status}")
        field = db.execute(
            "SELECT field_key FROM field_definitions WHERE field_key=?", (field_key,)
        ).fetchone()
        if field is None:
            raise KeyError(field_key)
        value = self._mapping_component_in_source(
            db, "detected_blocks", "block_id", value_block_id, source_id
        )
        if value is None:
            raise ValueError("Value block does not belong to the selected source")
        if label_block_id and self._mapping_component_in_source(
            db, "detected_blocks", "block_id", label_block_id, source_id
        ) is None:
            raise ValueError("Label block does not belong to the selected source")
        if unit_block_id and self._mapping_component_in_source(
            db, "detected_blocks", "block_id", unit_block_id, source_id
        ) is None:
            raise ValueError("Unit block does not belong to the selected source")
        if relation_id:
            relation = self._mapping_component_in_source(
                db, "detected_relations", "relation_id", relation_id, source_id
            )
            if relation is None:
                raise ValueError("Relation does not belong to the selected source")
            if str(relation["status"] or "proposed") == "rejected":
                raise ValueError("Deze relatie is afgekeurd. Herstel de afkeuring voordat je hem opnieuw mapt.")
            if str(relation["value_block_id"]) != str(value_block_id):
                raise ValueError("Relation and selected value block do not match")
            expected_label = str(relation["label_block_id"] or "")
            if label_block_id and expected_label and expected_label != str(label_block_id):
                raise ValueError("Relation and selected label block do not match")

        mapping_id = hashlib.sha256(f"{source_id}|{field_key}".encode("utf-8")).hexdigest()[:32]
        now = utc_now()
        existing = db.execute(
            "SELECT * FROM field_mappings WHERE source_id=? AND field_key=?",
            (source_id, field_key),
        ).fetchone()
        mapping_changed = bool(
            existing
            and (
                str(existing["relation_id"] or "") != str(relation_id or "")
                or str(existing["label_block_id"] or "") != str(label_block_id or "")
                or str(existing["value_block_id"] or "") != str(value_block_id or "")
                or str(existing["unit_block_id"] or "") != str(unit_block_id or "")
            )
        )
        if mapping_changed:
            self._invalidate_mapped_samples_in_connection(
                db, source_id, [field_key], reason="mapping_changed"
            )

        # One observed value must not silently feed multiple semantic fields. This
        # also protects manual block mappings, which do not have a relation_id.
        conflicts = db.execute(
            """
            SELECT * FROM field_mappings
            WHERE source_id=? AND field_key<>?
              AND (value_block_id=? OR (?<>'' AND relation_id=?))
            """,
            (source_id, field_key, value_block_id, relation_id, relation_id),
        ).fetchall()
        for conflict in conflicts:
            self._invalidate_mapped_samples_in_connection(
                db, source_id, [str(conflict["field_key"])], reason="relation_reassigned"
            )
            db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (conflict["mapping_id"],))

        db.execute(
            """
            INSERT INTO field_mappings(
                mapping_id, source_id, relation_id, field_key, label_block_id,
                value_block_id, unit_block_id, status, mapping_confidence,
                notes, profile_id, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, field_key) DO UPDATE SET
                mapping_id=excluded.mapping_id,
                relation_id=excluded.relation_id,
                label_block_id=excluded.label_block_id,
                value_block_id=excluded.value_block_id,
                unit_block_id=excluded.unit_block_id,
                status=excluded.status,
                mapping_confidence=excluded.mapping_confidence,
                notes=excluded.notes,
                profile_id=excluded.profile_id,
                updated_at=excluded.updated_at
            """,
            (
                mapping_id, source_id, relation_id, field_key, label_block_id,
                value_block_id, unit_block_id, status,
                max(0.0, min(1.0, float(mapping_confidence))), str(notes or ""),
                str(profile_id or ""), now, now,
            ),
        )
        if status == "confirmed" and label_block_id:
            label_row = db.execute(
                "SELECT text FROM detected_blocks WHERE block_id=? AND source_id=?",
                (label_block_id, source_id),
            ).fetchone()
            observed_label = str(label_row["text"] or "").strip() if label_row else ""
            if observed_label:
                field_row = db.execute(
                    "SELECT aliases_json FROM field_definitions WHERE field_key=?",
                    (field_key,),
                ).fetchone()
                try:
                    aliases = json.loads(field_row["aliases_json"] or "[]") if field_row else []
                except (TypeError, ValueError):
                    aliases = []
                if not isinstance(aliases, list):
                    aliases = []
                normalized_observed = re.sub(r"\s+", " ", observed_label.casefold()).strip()
                known = {
                    re.sub(r"\s+", " ", str(alias).casefold()).strip()
                    for alias in aliases
                }
                if normalized_observed and normalized_observed not in known:
                    aliases.append(observed_label)
                    db.execute(
                        "UPDATE field_definitions SET aliases_json=?, updated_at=? WHERE field_key=?",
                        (json.dumps(aliases, ensure_ascii=False), now, field_key),
                    )
        if status == "confirmed" and relation_id:
            self._record_relation_feedback_in_connection(
                db, source_id=source_id, relation_id=relation_id, verdict="accepted"
            )
        return mapping_id

    def upsert_mapping(
        self,
        *,
        source_id: str,
        field_key: str,
        value_block_id: str,
        label_block_id: str = "",
        unit_block_id: str = "",
        relation_id: str = "",
        status: str = "confirmed",
        mapping_confidence: float = 1.0,
        notes: str = "",
        profile_id: str = "",
    ) -> dict[str, Any]:
        with self.connect() as db:
            mapping_id = self._upsert_mapping_in_connection(
                db,
                source_id=source_id,
                field_key=field_key,
                value_block_id=value_block_id,
                label_block_id=label_block_id,
                unit_block_id=unit_block_id,
                relation_id=relation_id,
                status=status,
                mapping_confidence=mapping_confidence,
                notes=notes,
                profile_id=profile_id,
            )
        result = self.get_mapping(mapping_id)
        if result is None:
            raise RuntimeError("Mapping was not stored")
        return result

    def sync_relation_mappings(
        self,
        source_id: str,
        assignments: list[dict[str, str]],
    ) -> dict[str, int]:
        """Atomically synchronize relation mappings submitted by Mappingstudio.

        Every assignment must contain ``relation_id`` and may contain ``field_key``
        and ``notes``. An empty field_key explicitly removes the relation mapping.
        All relations/fields are validated before the first mutation, so a bad row
        can never leave a half-saved Mappingstudio form behind.
        """
        normalized: list[dict[str, str]] = []
        relation_ids: set[str] = set()
        selected_fields: set[str] = set()
        for item in assignments:
            relation_id = str(item.get("relation_id") or "").strip()
            field_key = str(item.get("field_key") or "").strip()
            notes = str(item.get("notes") or "")
            if not relation_id:
                raise ValueError("Mapping assignment is missing relation_id")
            if relation_id in relation_ids:
                raise ValueError(f"Relation occurs more than once in mapping form: {relation_id}")
            relation_ids.add(relation_id)
            if field_key:
                if field_key in selected_fields:
                    raise ValueError(f"Functional field occurs more than once in mapping form: {field_key}")
                selected_fields.add(field_key)
            normalized.append({"relation_id": relation_id, "field_key": field_key, "notes": notes})

        saved = 0
        removed = 0
        with self.connect() as db:
            # Preflight the complete request before changing anything.
            relation_rows: dict[str, sqlite3.Row] = {}
            for item in normalized:
                relation_id = item["relation_id"]
                relation = self._mapping_component_in_source(
                    db, "detected_relations", "relation_id", relation_id, source_id
                )
                if relation is None:
                    raise ValueError(f"Relation does not belong to the selected source: {relation_id}")
                relation_rows[relation_id] = relation
                field_key = item["field_key"]
                if field_key and db.execute(
                    "SELECT 1 FROM field_definitions WHERE field_key=? AND active=1", (field_key,)
                ).fetchone() is None:
                    raise ValueError(f"Unknown or inactive functional field: {field_key}")

            for item in normalized:
                relation_id = item["relation_id"]
                field_key = item["field_key"]
                current_rows = db.execute(
                    "SELECT * FROM field_mappings WHERE source_id=? AND relation_id=?",
                    (source_id, relation_id),
                ).fetchall()
                if not field_key:
                    for current in current_rows:
                        self._invalidate_mapped_samples_in_connection(
                            db, source_id, [str(current["field_key"])], reason="mapping_removed"
                        )
                        db.execute(
                            "DELETE FROM field_mappings WHERE mapping_id=?", (current["mapping_id"],)
                        )
                        removed += 1
                    continue

                relation = relation_rows[relation_id]
                current = next(
                    (row for row in current_rows if str(row["field_key"]) == field_key), None
                )
                if current is not None and str(current["status"]) == "confirmed" and str(current["notes"] or "") == item["notes"]:
                    continue
                self._upsert_mapping_in_connection(
                    db,
                    source_id=source_id,
                    field_key=field_key,
                    relation_id=relation_id,
                    label_block_id=str(relation["label_block_id"] or ""),
                    value_block_id=str(relation["value_block_id"]),
                    unit_block_id=str(relation["unit_block_id"] or ""),
                    status="confirmed",
                    mapping_confidence=float(relation["confidence"] or 0),
                    notes=item["notes"],
                )
                saved += 1
        return {"saved": saved, "removed": removed}

    def get_mapping(self, mapping_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute(
                """
                SELECT m.*, f.display_name, f.group_name, f.data_type, f.preferred_unit,
                       f.minimum_value, f.maximum_value,
                       lb.text AS label_text, lb.crop_path AS label_crop_path,
                       vb.text AS value_text, vb.crop_path AS value_crop_path,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       vb.confidence AS value_confidence,
                       ub.text AS unit_text, r.relation_type, r.table_id, r.row_index,
                       r.value_column_index, r.context_text AS relation_context, r.confidence AS relation_confidence
                FROM field_mappings m
                JOIN field_definitions f ON f.field_key=m.field_key
                LEFT JOIN detected_blocks lb ON lb.block_id=m.label_block_id
                JOIN detected_blocks vb ON vb.block_id=m.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=m.unit_block_id
                LEFT JOIN detected_relations r ON r.relation_id=m.relation_id
                WHERE m.mapping_id=?
                """,
                (mapping_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_mappings(self, source_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("m.source_id=?")
            params.append(source_id)
        if status:
            if status not in VALID_MAPPING_STATUSES:
                raise ValueError(f"Unsupported mapping status: {status}")
            clauses.append("m.status=?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT m.*, f.display_name, f.group_name, f.data_type, f.preferred_unit,
                       f.minimum_value, f.maximum_value,
                       lb.text AS label_text, lb.crop_path AS label_crop_path,
                       lb.context_text AS label_context,
                       vb.text AS value_text, vb.crop_path AS value_crop_path,
                       vb.x1 AS value_x1, vb.y1 AS value_y1, vb.x2 AS value_x2, vb.y2 AS value_y2,
                       vb.confidence AS value_confidence,
                       ub.text AS unit_text, r.context_text AS relation_context,
                       r.confidence AS relation_confidence, r.relation_type, r.table_id,
                       r.row_index, r.value_column_index
                FROM field_mappings m
                JOIN field_definitions f ON f.field_key=m.field_key
                LEFT JOIN detected_blocks lb ON lb.block_id=m.label_block_id
                JOIN detected_blocks vb ON vb.block_id=m.value_block_id
                LEFT JOIN detected_blocks ub ON ub.block_id=m.unit_block_id
                LEFT JOIN detected_relations r ON r.relation_id=m.relation_id
                {where}
                ORDER BY m.source_id, f.group_name, f.display_name
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_mapping(self, mapping_id: str) -> None:
        with self.connect() as db:
            existing = db.execute(
                "SELECT source_id, field_key FROM field_mappings WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
            if existing is not None:
                self._invalidate_mapped_samples_in_connection(
                    db, str(existing["source_id"]), [str(existing["field_key"])], reason="mapping_removed"
                )
            db.execute("DELETE FROM field_mappings WHERE mapping_id=?", (mapping_id,))

    def clear_suggested_mappings(self, source_id: str) -> int:
        with self.connect() as db:
            result = db.execute(
                "DELETE FROM field_mappings WHERE source_id=? AND status='suggested'", (source_id,)
            )
            return int(result.rowcount if result.rowcount is not None else 0)

    def clear_all_mappings(self) -> int:
        """Remove the complete generated mapping set before a rebuild.

        Canonical Detection-GT, Recognition-GT and relation feedback live in
        separate stores and are intentionally unaffected. Mapped samples are
        invalidated first so an old confirmed mapping cannot remain eligible
        for export after Mapping Studio is regenerated.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT source_id, field_key FROM field_mappings"
            ).fetchall()
            for row in rows:
                self._invalidate_mapped_samples_in_connection(
                    db,
                    str(row["source_id"]),
                    [str(row["field_key"])],
                    reason="mapping_dataset_rebuilt",
                )
            result = db.execute("DELETE FROM field_mappings")
            return int(result.rowcount if result.rowcount is not None else 0)

    def save_mapping_profile(
        self,
        *,
        profile_id: str,
        name: str,
        source_id: str,
        description: str = "",
    ) -> dict[str, Any]:
        profile_key = self._safe_field_key(profile_id).replace(".", "-")
        mappings = self.list_mappings(source_id, status="confirmed")
        if not mappings:
            raise ValueError("No confirmed mappings are available for this source")
        rules: list[dict[str, Any]] = []
        for item in mappings:
            # Keep only the semantic table/panel selector. The remaining OCR
            # header text belongs to this example image and must not become a
            # hidden per-source mapping rule for future DICOMs.
            relation_context = str(item.get("relation_context") or item.get("label_context") or "")
            semantic_context = relation_context.split("|", 1)[0].strip()
            rules.append(
                {
                    "field_key": item["field_key"],
                    "label_text": item.get("label_text") or "",
                    "label_normalized": re.sub(r"\s+", " ", str(item.get("label_text") or "").casefold()).strip(),
                    "context_text": semantic_context,
                    "relation_type": "same_line_right",
                    "value_rank": 1,
                    "preferred_unit": item.get("preferred_unit") or "",
                }
            )
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO mapping_profiles(
                    profile_id, name, description, schema_version, rules_json,
                    source_id, active, created_at, updated_at
                ) VALUES(?,?,?,'1.0',?,?,1,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    name=excluded.name, description=excluded.description,
                    rules_json=excluded.rules_json, source_id=excluded.source_id,
                    active=1, updated_at=excluded.updated_at
                """,
                (profile_key, str(name).strip() or profile_key, str(description or ""),
                 json.dumps(rules, ensure_ascii=False, indent=2), source_id, now, now),
            )
        result = self.get_mapping_profile(profile_key)
        if result is None:
            raise RuntimeError("Mapping profile was not stored")
        return result

    def get_mapping_profile(self, profile_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM mapping_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item["rules"] = json.loads(item.pop("rules_json") or "[]")
        except (TypeError, ValueError):
            item["rules"] = []
        return item

    def list_mapping_profiles(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM mapping_profiles ORDER BY updated_at DESC, name").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["rules"] = json.loads(item.pop("rules_json") or "[]")
            except (TypeError, ValueError):
                item["rules"] = []
            item["rule_count"] = len(item["rules"])
            result.append(item)
        return result


    def update_sample_recognition(
        self,
        sample_id: str,
        raw_ocr: str,
        raw_confidence: float,
        raw_variant: str = "recognition_only_mapped_generic",
    ) -> None:
        now = utc_now()
        with self.connect() as db:
            changed = db.execute(
                """
                UPDATE samples SET raw_ocr=?, raw_confidence=?, raw_variant=?,
                    status=CASE WHEN status='accepted' THEN 'pending' ELSE status END,
                    exact_label=CASE WHEN status='accepted' THEN NULL ELSE exact_label END,
                    reviewed_at=CASE WHEN status='accepted' THEN NULL ELSE reviewed_at END,
                    updated_at=?
                WHERE sample_id=?
                """,
                (str(raw_ocr), max(0.0, min(1.0, float(raw_confidence))), str(raw_variant), now, sample_id),
            ).rowcount
            if not changed:
                raise KeyError(sample_id)

    # ------------------------------------------------------------------
    # v3.7.0 Pipeline A: field localization / crop geometry
    # ------------------------------------------------------------------
    def replace_localization_detection(
        self,
        source: dict[str, Any],
        candidates: list[dict[str, Any]],
        tables: list[dict[str, Any]] | None = None,
    ) -> None:
        source_id = str(source["source_id"])
        now = utc_now()
        tables = tables or []
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO detection_sources(
                    source_id, image_width, image_height, render_path, detector_version,
                    token_count, block_count, relation_count, detected_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,0,?,?)
                ON CONFLICT(source_id) DO UPDATE SET
                    image_width=excluded.image_width, image_height=excluded.image_height,
                    render_path=excluded.render_path, detector_version=excluded.detector_version,
                    token_count=excluded.token_count, block_count=excluded.block_count,
                    relation_count=0, detected_at=excluded.detected_at,
                    review_completed=0, review_completed_at=NULL, updated_at=excluded.updated_at
                """,
                (
                    source_id, int(source["image_width"]), int(source["image_height"]),
                    str(source.get("render_path") or ""), str(source.get("detector_version") or ""),
                    int(source.get("token_count") or 0), len(candidates), now, now,
                ),
            )
            # Candidate IDs are deterministic. Preserve explicit reviews when the
            # same geometry reappears, but retire reviews whose candidate vanished.
            current_ids = {str(item["candidate_id"]) for item in candidates}
            existing_reviews = db.execute(
                "SELECT candidate_id FROM detection_reviews WHERE source_id=? AND candidate_id<>''",
                (source_id,),
            ).fetchall()
            for row in existing_reviews:
                candidate_id = str(row["candidate_id"])
                if candidate_id not in current_ids:
                    # Keep reviewed ground truth when machine geometry changes,
                    # but detach it from the vanished candidate so it remains
                    # visible/editable as persistent GT in Detection Review.
                    db.execute(
                        "UPDATE detection_reviews SET candidate_id='', updated_at=? WHERE source_id=? AND candidate_id=?",
                        (now, source_id, candidate_id),
                    )
                    db.execute(
                        "UPDATE detection_annotations SET candidate_id='', updated_at=? WHERE source_id=? AND candidate_id=? AND active=1",
                        (now, source_id, candidate_id),
                    )
            db.execute("DELETE FROM detection_candidates WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detection_table_cells WHERE source_id=?", (source_id,))
            db.execute("DELETE FROM detection_table_regions WHERE source_id=?", (source_id,))
            for item in candidates:
                db.execute(
                    """
                    INSERT INTO detection_candidates(
                        candidate_id, source_id, confidence, source_kind, source_refs_json,
                        crop_path, x1, y1, x2, y2, status, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?, ?, ?)
                    """,
                    (
                        str(item["candidate_id"]), source_id,
                        max(0.0, min(1.0, float(item.get("confidence") or 0))),
                        str(item.get("source_kind") or "text_geometry"),
                        json.dumps(item.get("source_refs") or [], ensure_ascii=False),
                        str(item.get("crop_path") or ""),
                        int(item["x1"]), int(item["y1"]), int(item["x2"]), int(item["y2"]),
                        str(item.get("status") or "proposed"), now, now,
                    ),
                )
            for table in tables:
                table_id = str(table["table_id"])
                db.execute(
                    """
                    INSERT INTO detection_table_regions(
                        table_id, source_id, confidence, x1, y1, x2, y2, created_at, updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        table_id, source_id, float(table.get("confidence") or 0),
                        int(table["x1"]), int(table["y1"]), int(table["x2"]), int(table["y2"]), now, now,
                    ),
                )
                for cell in table.get("cells") or []:
                    db.execute(
                        """
                        INSERT INTO detection_table_cells(
                            cell_id, table_id, source_id, row_index, column_index, confidence,
                            x1, y1, x2, y2, created_at, updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            str(cell["cell_id"]), table_id, source_id,
                            int(cell.get("row_index", -1)), int(cell.get("column_index", -1)),
                            float(cell.get("confidence") or 0), int(cell["x1"]), int(cell["y1"]),
                            int(cell["x2"]), int(cell["y2"]), now, now,
                        ),
                    )

    def list_detection_candidates(self, source_id: str, *, include_rejected: bool = True) -> list[dict[str, Any]]:
        where = "" if include_rejected else "AND c.status<>'rejected'"
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT c.*, r.review_id, r.review_status, r.reason_code,
                       r.relevance_status, r.relevance_reason, r.notes AS review_notes,
                       r.corrected_x1, r.corrected_y1, r.corrected_x2, r.corrected_y2, r.reviewed_at
                FROM detection_candidates c
                LEFT JOIN detection_reviews r ON r.source_id=c.source_id AND r.candidate_id=c.candidate_id
                WHERE c.source_id=? {where}
                ORDER BY c.y1, c.x1, c.y2, c.x2
                """,
                (source_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["source_refs"] = json.loads(item.pop("source_refs_json") or "[]")
            except (TypeError, ValueError):
                item["source_refs"] = []
            result.append(item)
        return result

    def get_detection_candidate(self, source_id: str, candidate_id: str) -> dict[str, Any] | None:
        items = [item for item in self.list_detection_candidates(source_id) if item["candidate_id"] == candidate_id]
        return items[0] if items else None

    def list_detection_table_geometry(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        with self.connect() as db:
            regions = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_regions WHERE source_id=? ORDER BY y1,x1", (source_id,)
            ).fetchall()]
            cells = [dict(row) for row in db.execute(
                "SELECT * FROM detection_table_cells WHERE source_id=? ORDER BY table_id,row_index,column_index,y1,x1",
                (source_id,),
            ).fetchall()]
        return {"regions": regions, "cells": cells}

    def review_detection_candidate(
        self,
        *,
        source_id: str,
        candidate_id: str,
        review_status: str,
        corrected_box: tuple[int, int, int, int] | None = None,
        reason_code: str = "",
        relevance_status: str = "relevant",
        relevance_reason: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        """Store explicit project-specific localization supervision.

        Correct/adjusted/relevant boxes are positive examples. Rejected boxes and
        technically correct but out-of-scope boxes are negative examples for the
        active project/use-case. Review reasons remain optional analytics metadata.
        Unreviewed candidates never become training data.
        """
        status = str(review_status).strip().lower()
        if status not in VALID_DETECTION_REVIEW_STATUSES - {"added"}:
            raise ValueError(f"Unsupported detection review status: {review_status}")
        reason = str(reason_code or "").strip().lower()
        if reason not in VALID_DETECTION_REVIEW_REASONS:
            raise ValueError("Choose a valid detection review reason")
        relevance = str(relevance_status or "relevant").strip().lower()
        if relevance not in VALID_DETECTION_RELEVANCE_STATUSES:
            raise ValueError(f"Unsupported detection relevance status: {relevance_status}")
        scope_reason = str(relevance_reason or "").strip().lower()
        if scope_reason not in VALID_DETECTION_RELEVANCE_REASONS:
            raise ValueError("Choose a valid relevance reason")
        if status == "rejected":
            relevance = "unreviewed"
            scope_reason = ""
        elif relevance == "unreviewed":
            # A geometrically accepted box needs an explicit scope decision.
            # Preserve backwards compatibility for API/CLI callers by treating
            # omitted scope as relevant.
            relevance = "relevant"

        candidate = self.get_detection_candidate(source_id, candidate_id)
        if candidate is None:
            raise KeyError(candidate_id)
        width = int((self.get_detection_source(source_id) or {}).get("image_width") or 0)
        height = int((self.get_detection_source(source_id) or {}).get("image_height") or 0)
        original = (int(candidate["x1"]), int(candidate["y1"]), int(candidate["x2"]), int(candidate["y2"]))
        corrected = tuple(int(value) for value in (corrected_box or original))
        x1, y1, x2, y2 = corrected
        x1, x2 = sorted((max(0, x1), min(width, x2)))
        y1, y2 = sorted((max(0, y1), min(height, y2)))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Corrected detection box must have a positive width and height")
        corrected = (x1, y1, x2, y2)
        if status == "correct":
            corrected = original
        if status == "adjusted" and corrected == original:
            status = "correct"

        now = utc_now()
        review_id = hashlib.sha256(f"{source_id}|{candidate_id}".encode("utf-8")).hexdigest()[:32]
        annotation_id = hashlib.sha256(f"annotation|{source_id}|{candidate_id}".encode("utf-8")).hexdigest()[:32]
        training_role = "negative" if status == "rejected" or relevance == "irrelevant" else "positive"
        with self.connect() as db:
            db.execute(
                "UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?",
                (now, source_id),
            )
            db.execute(
                """
                INSERT INTO detection_reviews(
                    review_id, source_id, candidate_id, review_status, reason_code,
                    relevance_status, relevance_reason, notes,
                    original_x1, original_y1, original_x2, original_y2,
                    corrected_x1, corrected_y1, corrected_x2, corrected_y2,
                    reviewed_at, created_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(review_id) DO UPDATE SET
                    review_status=excluded.review_status, reason_code=excluded.reason_code,
                    relevance_status=excluded.relevance_status, relevance_reason=excluded.relevance_reason,
                    notes=excluded.notes, corrected_x1=excluded.corrected_x1,
                    corrected_y1=excluded.corrected_y1, corrected_x2=excluded.corrected_x2,
                    corrected_y2=excluded.corrected_y2, reviewed_at=excluded.reviewed_at,
                    updated_at=excluded.updated_at
                """,
                (review_id, source_id, candidate_id, status, reason, relevance, scope_reason, str(notes or ""),
                 *original, *corrected, now, now, now),
            )
            candidate_state = "rejected" if status == "rejected" else ("irrelevant" if relevance == "irrelevant" else "reviewed")
            db.execute(
                "UPDATE detection_candidates SET status=?, updated_at=? WHERE source_id=? AND candidate_id=?",
                (candidate_state, now, source_id, candidate_id),
            )
            # Keep one active reviewed region per physical field. Positive and
            # negative project-specific examples both participate in deduplication.
            existing_annotations = db.execute(
                "SELECT annotation_id,x1,y1,x2,y2 FROM detection_annotations WHERE source_id=? AND active=1 AND annotation_id<>?",
                (source_id, annotation_id),
            ).fetchall()
            new_area = max(1, (corrected[2] - corrected[0]) * (corrected[3] - corrected[1]))
            for old in existing_annotations:
                ix1, iy1 = max(corrected[0], int(old["x1"])), max(corrected[1], int(old["y1"]))
                ix2, iy2 = min(corrected[2], int(old["x2"])), min(corrected[3], int(old["y2"]))
                intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                old_area = max(1, (int(old["x2"]) - int(old["x1"])) * (int(old["y2"]) - int(old["y1"])))
                overlap = intersection / max(1, min(new_area, old_area))
                if overlap >= 0.85:
                    db.execute(
                        "UPDATE detection_annotations SET active=0, updated_at=? WHERE annotation_id=?",
                        (now, str(old["annotation_id"])),
                    )
            db.execute(
                """
                INSERT INTO detection_annotations(
                    annotation_id, source_id, candidate_id, review_id, provenance, training_role,
                    x1,y1,x2,y2,active,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,1,?,?)
                ON CONFLICT(annotation_id) DO UPDATE SET
                    review_id=excluded.review_id, provenance=excluded.provenance, training_role=excluded.training_role,
                    x1=excluded.x1,y1=excluded.y1,x2=excluded.x2,y2=excluded.y2,
                    active=1,updated_at=excluded.updated_at
                """,
                (annotation_id, source_id, candidate_id, review_id, status, training_role, *corrected, now, now),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth of scope is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return self.get_detection_candidate(source_id, candidate_id) or candidate

    def add_detection_annotation(
        self,
        *,
        source_id: str,
        box: tuple[int, int, int, int],
        reason_code: str = "",
        notes: str = "",
    ) -> dict[str, Any]:
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        width, height = int(source["image_width"]), int(source["image_height"])
        x1, y1, x2, y2 = (int(value) for value in box)
        x1, x2 = sorted((max(0, x1), min(width, x2)))
        y1, y2 = sorted((max(0, y1), min(height, y2)))
        if x2 <= x1 or y2 <= y1:
            raise ValueError("Added detection box must have a positive width and height")
        now = utc_now()
        seed = f"manual|{source_id}|{x1},{y1},{x2},{y2}|{now}"
        review_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
        annotation_id = hashlib.sha256(("annotation|" + seed).encode("utf-8")).hexdigest()[:32]
        with self.connect() as db:
            db.execute("UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?", (now, source_id))
            db.execute(
                """
                INSERT INTO detection_reviews(
                    review_id,source_id,candidate_id,review_status,reason_code,relevance_status,relevance_reason,notes,
                    original_x1,original_y1,original_x2,original_y2,
                    corrected_x1,corrected_y1,corrected_x2,corrected_y2,
                    reviewed_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (review_id, source_id, "", "added", str(reason_code or ""), "relevant", "", str(notes or ""),
                 x1,y1,x2,y2,x1,y1,x2,y2,now,now,now),
            )
            db.execute(
                """
                INSERT INTO detection_annotations(
                    annotation_id,source_id,candidate_id,review_id,provenance,training_role,x1,y1,x2,y2,active,created_at,updated_at
                ) VALUES(?,?,'',?,'added','positive',?,?,?,?,1,?,?)
                """,
                (annotation_id, source_id, review_id, x1,y1,x2,y2,now,now),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return {
            "annotation_id": annotation_id, "review_id": review_id, "source_id": source_id,
            "review_status": "added", "provenance": "added", "training_role": "positive",
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "notes": str(notes or ""), "reason_code": str(reason_code or ""),
        }

    def update_manual_detection_annotation(
        self,
        annotation_id: str,
        *,
        box: tuple[int, int, int, int],
    ) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM detection_annotations WHERE annotation_id=? AND active=1",
                (annotation_id,),
            ).fetchone()
            if row is None or str(row["candidate_id"] or ""):
                raise KeyError(annotation_id)
            source = db.execute(
                "SELECT image_width,image_height FROM detection_sources WHERE source_id=?",
                (str(row["source_id"]),),
            ).fetchone()
            if source is None:
                raise KeyError(str(row["source_id"]))
            width, height = int(source["image_width"]), int(source["image_height"])
            x1, y1, x2, y2 = (int(value) for value in box)
            x1, x2 = sorted((max(0, x1), min(width, x2)))
            y1, y2 = sorted((max(0, y1), min(height, y2)))
            if x2 <= x1 or y2 <= y1:
                raise ValueError("Manual detection box must have a positive width and height")
            now = utc_now()
            db.execute(
                """
                UPDATE detection_annotations
                SET x1=?,y1=?,x2=?,y2=?,updated_at=?
                WHERE annotation_id=?
                """,
                (x1, y1, x2, y2, now, annotation_id),
            )
            review_id = str(row["review_id"] or "")
            if review_id:
                db.execute(
                    """
                    UPDATE detection_reviews
                    SET corrected_x1=?,corrected_y1=?,corrected_x2=?,corrected_y2=?,updated_at=?
                    WHERE review_id=?
                    """,
                    (x1, y1, x2, y2, now, review_id),
                )
            db.execute(
                "UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?",
                (now, str(row["source_id"])),
            )
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )
        return {
            "annotation_id": annotation_id,
            "review_id": str(row["review_id"] or ""),
            "source_id": str(row["source_id"]),
            "review_status": "added",
            "provenance": str(row["provenance"] or "added"),
            "training_role": str(row["training_role"] or "positive"),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        }

    def delete_manual_detection_annotation(self, annotation_id: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM detection_annotations WHERE annotation_id=?", (annotation_id,)).fetchone()
            if row is None or str(row["candidate_id"] or ""):
                raise KeyError(annotation_id)
            now = utc_now()
            db.execute("UPDATE detection_annotations SET active=0, updated_at=? WHERE annotation_id=?", (now, annotation_id))
            db.execute("UPDATE detection_sources SET review_completed=0, review_completed_at=NULL, updated_at=? WHERE source_id=?", (now, str(row["source_id"])))
        self.set_detection_gate(
            False,
            reason="Detection ground truth is gewijzigd; evalueer en activeer de field detector opnieuw.",
        )

    def accept_unreviewed_detection_candidates(self, source_id: str) -> int:
        """Accept every still-open machine candidate for one source as positive GT.

        This is intentionally source-scoped and is used only when the reviewer
        explicitly finishes an image with the "include remaining" option enabled.
        Explicit Not relevant / Incorrect / adjusted decisions are preserved.
        """
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        candidates = self.list_detection_candidates(source_id, include_rejected=True)
        pending = [item for item in candidates if not str(item.get("review_status") or "").strip()]
        for item in pending:
            self.review_detection_candidate(
                source_id=source_id,
                candidate_id=str(item["candidate_id"]),
                review_status="correct",
                relevance_status="relevant",
            )
        return len(pending)

    def set_detection_source_review_completed(
        self,
        source_id: str,
        completed: bool = True,
        *,
        accept_unreviewed: bool = False,
    ) -> dict[str, Any]:
        source = self.get_detection_source(source_id)
        if source is None:
            raise KeyError(source_id)
        if completed and accept_unreviewed:
            self.accept_unreviewed_detection_candidates(source_id)
        now = utc_now()
        if completed:
            counts = self.detection_review_counts(source_id)
            if int(counts.get("pending") or 0) > 0:
                raise ValueError(f"Nog {counts['pending']} onbeoordeelde ROI's")
        with self.connect() as db:
            db.execute(
                "UPDATE detection_sources SET review_completed=?, review_completed_at=?, updated_at=? WHERE source_id=?",
                (1 if completed else 0, now if completed else None, now, source_id),
            )
        return self.get_detection_source(source_id) or source

    def list_detection_annotations(
        self,
        source_id: str | None = None,
        *,
        active_only: bool = True,
        include_ignored: bool = False,
    ) -> list[dict[str, Any]]:
        """Return reviewed Pipeline-A geometry.

        By default only positive project-specific localization ground truth is returned.
        Callers that need audit/UI or explicit negative examples can request
        ``include_ignored=True`` (legacy parameter name kept for compatibility).
        """
        clauses: list[str] = []
        params: list[Any] = []
        if source_id:
            clauses.append("a.source_id=?")
            params.append(source_id)
        if active_only:
            clauses.append("a.active=1")
        if not include_ignored:
            clauses.append("a.training_role='positive'")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            rows = db.execute(
                f"""
                SELECT a.*, r.review_status, r.reason_code, r.relevance_status, r.relevance_reason,
                       r.notes, r.reviewed_at, s.render_path, s.image_width, s.image_height
                FROM detection_annotations a
                LEFT JOIN detection_reviews r ON r.review_id=a.review_id
                JOIN detection_sources s ON s.source_id=a.source_id
                {where}
                ORDER BY a.source_id,a.y1,a.x1
                """, params,
            ).fetchall()
        return [dict(row) for row in rows]

    def list_detection_reviews(self, source_id: str | None = None) -> list[dict[str, Any]]:
        if source_id:
            query, params = "SELECT * FROM detection_reviews WHERE source_id=? ORDER BY reviewed_at", (source_id,)
        else:
            query, params = "SELECT * FROM detection_reviews ORDER BY reviewed_at", ()
        with self.connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def detection_review_counts(self, source_id: str | None = None) -> dict[str, int]:
        """Count geometry review and workflow relevance independently."""
        with self.connect() as db:
            params: tuple[Any, ...] = (source_id,) if source_id else ()
            candidate_where = "WHERE c.source_id=?" if source_id else ""
            candidate_total = int(db.execute(
                f"SELECT COUNT(*) FROM detection_candidates c {candidate_where}", params
            ).fetchone()[0])
            rows = db.execute(
                f"""
                SELECT r.review_status, r.relevance_status, COUNT(*) amount
                FROM detection_reviews r
                JOIN detection_candidates c
                  ON c.source_id=r.source_id AND c.candidate_id=r.candidate_id
                {('WHERE r.source_id=?' if source_id else '')}
                GROUP BY r.review_status, r.relevance_status
                """, params,
            ).fetchall()
            added_params: tuple[Any, ...] = (source_id,) if source_id else ()
            added = int(db.execute(
                f"SELECT COUNT(*) FROM detection_reviews WHERE review_status='added' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            positive_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND training_role='positive' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            ignored_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND training_role='negative' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
            persistent_annotations = int(db.execute(
                f"SELECT COUNT(*) FROM detection_annotations WHERE active=1 AND candidate_id='' {('AND source_id=?' if source_id else '')}",
                added_params,
            ).fetchone()[0])
        result = {status: 0 for status in VALID_DETECTION_REVIEW_STATUSES}
        result.update({"relevant": 0, "irrelevant": 0})
        for row in rows:
            status = str(row["review_status"])
            relevance = str(row["relevance_status"] or "relevant")
            amount = int(row["amount"])
            if status in result:
                result[status] += amount
            if status in {"correct", "adjusted"} and relevance in {"relevant", "irrelevant"}:
                result[relevance] += amount
        result["added"] = added
        candidate_reviewed = result["correct"] + result["adjusted"] + result["rejected"]
        result["candidate_total"] = candidate_total
        result["candidate_reviewed"] = candidate_reviewed
        result["pending"] = max(0, candidate_total - candidate_reviewed)
        result["positive"] = positive_annotations
        result["negative"] = ignored_annotations
        result["ignored"] = ignored_annotations  # backwards-compatible UI key
        result["persistent"] = persistent_annotations
        result["total_reviews"] = candidate_reviewed + result["added"]
        return result

    def detection_review_counts_by_source(self) -> dict[str, dict[str, int]]:
        """Return the same review counters as detection_review_counts, grouped in bulk.

        The review overview used to execute 5+ SQL statements per source. This
        keeps page cost essentially constant as the number of DICOM sources grows.
        """
        with self.connect() as db:
            source_ids = [str(row[0]) for row in db.execute(
                "SELECT source_id FROM detection_sources"
            ).fetchall()]
            candidate_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_candidates GROUP BY source_id"
            ).fetchall()
            review_rows = db.execute(
                """
                SELECT r.source_id, r.review_status, r.relevance_status, COUNT(*) amount
                FROM detection_reviews r
                JOIN detection_candidates c
                  ON c.source_id=r.source_id AND c.candidate_id=r.candidate_id
                GROUP BY r.source_id, r.review_status, r.relevance_status
                """
            ).fetchall()
            added_rows = db.execute(
                """
                SELECT source_id, COUNT(*) amount
                FROM detection_reviews
                WHERE review_status='added'
                GROUP BY source_id
                """
            ).fetchall()
            annotation_rows = db.execute(
                """
                SELECT source_id, training_role, COUNT(*) amount,
                       SUM(CASE WHEN candidate_id='' THEN 1 ELSE 0 END) persistent
                FROM detection_annotations
                WHERE active=1
                GROUP BY source_id, training_role
                """
            ).fetchall()

        def empty() -> dict[str, int]:
            result = {status: 0 for status in VALID_DETECTION_REVIEW_STATUSES}
            result.update({
                "relevant": 0, "irrelevant": 0, "added": 0,
                "candidate_total": 0, "candidate_reviewed": 0, "pending": 0,
                "positive": 0, "negative": 0, "ignored": 0, "persistent": 0,
                "total_reviews": 0,
            })
            return result

        result = {source_id: empty() for source_id in source_ids}
        for row in candidate_rows:
            result.setdefault(str(row["source_id"]), empty())["candidate_total"] = int(row["amount"])
        for row in review_rows:
            item = result.setdefault(str(row["source_id"]), empty())
            status = str(row["review_status"])
            relevance = str(row["relevance_status"] or "relevant")
            amount = int(row["amount"])
            if status in item:
                item[status] += amount
            if status in {"correct", "adjusted"} and relevance in {"relevant", "irrelevant"}:
                item[relevance] += amount
        for row in added_rows:
            result.setdefault(str(row["source_id"]), empty())["added"] = int(row["amount"])
        for row in annotation_rows:
            item = result.setdefault(str(row["source_id"]), empty())
            role = str(row["training_role"] or "positive")
            amount = int(row["amount"])
            if role == "positive":
                item["positive"] += amount
            elif role == "negative":
                item["negative"] += amount
                item["ignored"] += amount
            item["persistent"] += int(row["persistent"] or 0)
        for item in result.values():
            item["candidate_reviewed"] = item["correct"] + item["adjusted"] + item["rejected"]
            item["pending"] = max(0, item["candidate_total"] - item["candidate_reviewed"])
            item["total_reviews"] = item["candidate_reviewed"] + item["added"]
        return result

    def detection_table_counts_by_source(self) -> dict[str, dict[str, int]]:
        """Count table regions/cells for all sources without N+1 queries."""
        with self.connect() as db:
            region_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_table_regions GROUP BY source_id"
            ).fetchall()
            cell_rows = db.execute(
                "SELECT source_id, COUNT(*) amount FROM detection_table_cells GROUP BY source_id"
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in region_rows:
            result.setdefault(str(row["source_id"]), {"regions": 0, "cells": 0})["regions"] = int(row["amount"])
        for row in cell_rows:
            result.setdefault(str(row["source_id"]), {"regions": 0, "cells": 0})["cells"] = int(row["amount"])
        return result

    def save_localization_dataset(self, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO localization_datasets(
                    dataset_id,path,image_count,annotation_count,negative_image_count,split_json,manifest_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload["dataset_id"]), str(payload["path"]), int(payload.get("image_count") or 0),
                    int(payload.get("annotation_count") or 0), int(payload.get("negative_image_count") or 0),
                    json.dumps(payload.get("splits") or {}, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False), str(payload.get("created_at") or utc_now()),
                ),
            )

    def list_localization_datasets(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM localization_datasets ORDER BY created_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            for source,target in (("split_json","splits"),("manifest_json","manifest")):
                try: item[target]=json.loads(item.pop(source) or "{}")
                except (TypeError,ValueError): item[target]={}
            manifest = item.get("manifest") if isinstance(item.get("manifest"), dict) else {}
            item["ignored_annotation_count"] = int(manifest.get("ignored_annotation_count") or 0)
            item["coco_annotation_count"] = int(manifest.get("coco_annotation_count") or item.get("annotation_count") or 0)
            result.append(item)
        return result

    def save_localization_evaluation(self, payload: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO localization_evaluations(
                    evaluation_id,model_id,dataset_id,kind,split,metrics_json,predictions_path,created_at
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    str(payload["evaluation_id"]), str(payload.get("model_id") or ""),
                    str(payload.get("dataset_id") or ""), str(payload.get("kind") or "baseline"),
                    str(payload.get("split") or "test"), json.dumps(payload.get("metrics") or {}, ensure_ascii=False),
                    str(payload.get("predictions_path") or ""), str(payload.get("created_at") or utc_now()),
                ),
            )

    def list_localization_evaluations(self, kind: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if kind:
                rows=db.execute("SELECT * FROM localization_evaluations WHERE kind=? ORDER BY created_at DESC",(kind,)).fetchall()
            else:
                rows=db.execute("SELECT * FROM localization_evaluations ORDER BY created_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
            except (TypeError,ValueError): item["metrics"]={}
            result.append(item)
        return result

    def register_localization_model(self, payload: dict[str, Any], *, activate: bool = False) -> None:
        now=utc_now()
        with self.connect() as db:
            if activate:
                db.execute("UPDATE localization_models SET active=0")
            db.execute(
                """
                INSERT INTO localization_models(
                    model_id,model_name,path,status,device,dataset_id,metrics_json,active,registered_at,activated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(model_id) DO UPDATE SET
                    model_name=excluded.model_name,path=excluded.path,status=excluded.status,
                    device=excluded.device,dataset_id=excluded.dataset_id,metrics_json=excluded.metrics_json,
                    active=excluded.active,activated_at=excluded.activated_at
                """,
                (
                    str(payload["model_id"]), str(payload.get("model_name") or "PicoDet-S"),
                    str(payload.get("path") or ""), str(payload.get("status") or "registered"),
                    str(payload.get("device") or ""), str(payload.get("dataset_id") or ""),
                    json.dumps(payload.get("metrics") or {}, ensure_ascii=False), 1 if activate else 0,
                    str(payload.get("registered_at") or now), now if activate else payload.get("activated_at"),
                ),
            )
            if activate:
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES('active_localization_model_id',?)", (str(payload["model_id"]),))

    def active_localization_model(self) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_models WHERE active=1 ORDER BY activated_at DESC LIMIT 1").fetchone()
        if row is None: return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def list_localization_models(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows=db.execute("SELECT * FROM localization_models ORDER BY active DESC,registered_at DESC").fetchall()
        result=[]
        for row in rows:
            item=dict(row)
            try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
            except (TypeError,ValueError): item["metrics"]={}
            result.append(item)
        return result

    def get_localization_model(self, model_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_models WHERE model_id=?", (str(model_id),)).fetchone()
        if row is None:
            return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def get_localization_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row=db.execute("SELECT * FROM localization_evaluations WHERE evaluation_id=?", (str(evaluation_id),)).fetchone()
        if row is None:
            return None
        item=dict(row)
        try: item["metrics"]=json.loads(item.pop("metrics_json") or "{}")
        except (TypeError,ValueError): item["metrics"]={}
        return item

    def delete_localization_dataset_record(self, dataset_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM localization_datasets WHERE dataset_id=?", (str(dataset_id),))

    def delete_localization_evaluation(self, evaluation_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM localization_evaluations WHERE evaluation_id=?", (str(evaluation_id),))

    def delete_localization_model(self, model_id: str) -> None:
        with self.connect() as db:
            row=db.execute("SELECT active FROM localization_models WHERE model_id=?", (str(model_id),)).fetchone()
            if row is not None and int(row["active"] or 0):
                raise ValueError("Active localization model cannot be deleted; activate another model first")
            db.execute("DELETE FROM localization_models WHERE model_id=?", (str(model_id),))
            current=db.execute("SELECT value FROM metadata WHERE key='active_localization_model_id'").fetchone()
            if current is not None and str(current["value"] or "") == str(model_id):
                db.execute("DELETE FROM metadata WHERE key='active_localization_model_id'")

    def set_detection_gate(self, ready: bool, *, reason: str, evaluation_id: str = "") -> None:
        updated_at = utc_now()
        values = {
            "detection_gate_ready":"1" if ready else "0",
            "detection_gate_reason":str(reason or ""),
            "detection_gate_evaluation_id":str(evaluation_id or ""),
            "detection_gate_updated_at":updated_at,
        }
        with self.connect() as db:
            for key,value in values.items():
                db.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)",(key,value))
        # Host-side PowerShell actions cannot rely on a local sqlite3 executable.
        # Mirror the authoritative DB state to a small JSON gate file so direct
        # menu actions are blocked before Docker value processing starts.
        gate_file = self.path.parent / "detection_gate.json"
        temporary = gate_file.with_suffix(".json.tmp")
        temporary.write_text(json.dumps({
            "ready": bool(ready), "reason": str(reason or ""),
            "evaluation_id": str(evaluation_id or ""), "updated_at": updated_at,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(gate_file)

    def detection_gate(self) -> dict[str, Any]:
        with self.connect() as db:
            rows=db.execute("SELECT key,value FROM metadata WHERE key LIKE 'detection_gate_%'").fetchall()
        values={str(row["key"]):str(row["value"]) for row in rows}
        return {
            "ready": values.get("detection_gate_ready") == "1",
            "reason": values.get("detection_gate_reason", "Nog geen localization-evaluatie die de kwaliteitspoort haalt."),
            "evaluation_id": values.get("detection_gate_evaluation_id", ""),
            "updated_at": values.get("detection_gate_updated_at", ""),
        }
