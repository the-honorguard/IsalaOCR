from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# Re-exported for backward compatibility: existing call sites elsewhere do
# `from .db import utc_now` / `from isala_ocr.training.db import SCHEMA_VERSION`
# etc. The definitions themselves live in db_constants.py so the method
# mixins below (db_samples.py and friends) can import them without a
# circular import back through this module.
from .db_constants import (  # noqa: F401
    MISSING_MARKERS,
    SCHEMA_VERSION,
    VALID_CONTENT_CLASSES,
    VALID_DETECTION_RELEVANCE_REASONS,
    VALID_DETECTION_RELEVANCE_STATUSES,
    VALID_DETECTION_REVIEW_REASONS,
    VALID_DETECTION_REVIEW_STATUSES,
    VALID_DETECTION_TRAINING_ROLES,
    VALID_FIELD_TYPES,
    VALID_HEADER_REVIEW_STATUSES,
    VALID_MAPPING_STATUSES,
    VALID_OCR_CONTENT_FILTERS,
    VALID_STATUSES,
    utc_now,
    validate_exact_label,
)
from .db_detection_gate import DetectionGateMixin
from .db_detection_review import DetectionReviewMixin
from .db_field_definitions import FieldDefinitionsMixin
from .db_generic_detection import GenericDetectionMixin
from .db_localization import LocalizationMixin
from .db_mappings import MappingsMixin
from .db_relation_feedback import RelationFeedbackMixin
from .db_samples import SamplesMixin


class TrainingDatabase(
    SamplesMixin,
    FieldDefinitionsMixin,
    GenericDetectionMixin,
    RelationFeedbackMixin,
    MappingsMixin,
    DetectionReviewMixin,
    LocalizationMixin,
    DetectionGateMixin,
):
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initializing = False
        # (st_dev, st_ino) of the database file the last time we confirmed its
        # schema was current. connect() is the hottest method in this class
        # (called on every database access), so re-running the full
        # _schema_is_current() check - a second sqlite3 connection plus a
        # PRAGMA round-trip - on every single call was measurable overhead for
        # no benefit in the overwhelmingly common case where the file hasn't
        # changed since we last checked it. A cheap stat() is enough to notice
        # the file being replaced (project reset) and fall back to the real check.
        self._schema_confirmed_identity: tuple[int, int] | None = None
        self.initialize()

    def _file_identity(self) -> tuple[int, int] | None:
        try:
            stat = self.path.stat()
        except OSError:
            return None
        if stat.st_size == 0:
            return None
        return (stat.st_dev, stat.st_ino)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        # The project reset may remove the SQLite file while the long-lived
        # WebUI process is still running. Recreate the schema before opening a
        # new connection instead of allowing every request to fail with
        # "no such table".
        if not self._initializing:
            identity = self._file_identity()
            if identity is None or identity != self._schema_confirmed_identity:
                if self._schema_is_current():
                    self._schema_confirmed_identity = identity
                else:
                    self.initialize()
                    self._schema_confirmed_identity = self._file_identity()
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

