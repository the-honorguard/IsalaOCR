"""Compatibility shim for the optional application-processing layer.

Semantic field mapping is not part of model training. Existing imports are kept
working while callers migrate to :mod:`isala_ocr.application_processing`.
"""

from ..application_processing.semantics import (
    MISSING_VALUE_MARKERS,
    is_missing_value_text,
    schema_candidate_score,
)

__all__ = ["MISSING_VALUE_MARKERS", "is_missing_value_text", "schema_candidate_score"]
