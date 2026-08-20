"""Optional postprocessing layer built on top of trained IsalaOCR model output.

The model factory under :mod:`isala_ocr.training` must stay usable without this
package.  Application-specific field semantics, aliases, units, missing-value
rules and structured-output mapping live here so they can be enabled later as a
separate deployment phase without becoming model-training requirements.
"""

from .lateral import (
    ambiguous_lateral_suffixes,
    field_lateral_side,
    field_lateral_suffix,
    lateral_candidate_allowed,
    relation_lateral_side,
)
from .semantics import MISSING_VALUE_MARKERS, is_missing_value_text, schema_candidate_score

__all__ = [
    "MISSING_VALUE_MARKERS",
    "ambiguous_lateral_suffixes",
    "field_lateral_side",
    "field_lateral_suffix",
    "is_missing_value_text",
    "lateral_candidate_allowed",
    "relation_lateral_side",
    "schema_candidate_score",
]
