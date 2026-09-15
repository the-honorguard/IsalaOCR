"""Shared constants and small helpers for the training database.

Split out of ``db.py`` so that the ``TrainingDatabase`` method mixins
(``db_samples.py``, ``db_field_definitions.py``, ...) can import these
without creating a circular import with ``db.py`` itself, which imports the
mixins. ``db.py`` re-exports every name here so existing call sites
(``from .db import utc_now``, ``from isala_ocr.training.db import
SCHEMA_VERSION``, etc.) keep working unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

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
