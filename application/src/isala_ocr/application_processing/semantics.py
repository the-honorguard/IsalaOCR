from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable

from ..training.generic_detection import normalize_text

MISSING_VALUE_MARKERS = ("-", "–", "—")

_LEADING_NUMBER_RE = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*")


def is_missing_value_text(value: object) -> bool:
    """Return True only for explicit empty-value markers, never negatives."""
    return str(value or "").strip() in MISSING_VALUE_MARKERS


def _normalize_unit(value: str) -> str:
    """Normalize a unit string while keeping "/" meaningful (unlike
    ``normalize_text``, which flattens it to whitespace and would make "ml"
    and "ml/m2" indistinguishable -- see ``schema_candidate_score``'s
    docstring on ``unit_match``).
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("²", "2").replace("·", "*")
    return re.sub(r"\s+", "", text)


def _value_unit_suffix(raw_value: str) -> str:
    """The unit text trailing a value's leading number, e.g. "ml/m2" from "93.1 ml/m2"."""
    return _LEADING_NUMBER_RE.sub("", str(raw_value or ""), count=1)


def schema_candidate_score(
    field: dict[str, Any],
    relation: dict[str, Any],
    *,
    similarity: Callable[[str, str], float],
    context_score: Callable[[str, str], float],
    feedback_multiplier: float = 1.0,
) -> tuple[float, dict[str, Any]]:
    """Score application-schema evidence without teaching it to the OCR model.

    The scorer is deliberately schema driven. It knows only generic evidence
    classes (aliases, context, units, relation confidence and missing markers),
    never report-specific labels such as HR, EF, glucose, etc. A deployment/use-
    case profile supplies those values later.
    """
    aliases = [str(field.get("display_name") or "")]
    aliases.extend(str(item or "") for item in field.get("aliases", []))
    aliases = [item for item in aliases if normalize_text(item)]

    label = str(relation.get("label_text") or "")
    normalized_label = normalize_text(label)
    label_score = max((similarity(label, alias) for alias in aliases), default=0.0)
    exact_alias = bool(normalized_label) and any(
        normalized_label == normalize_text(alias) for alias in aliases
    )

    context_value = context_score(
        str(field.get("group_name") or ""),
        str(relation.get("context_text") or ""),
    )
    preferred_unit_raw = str(field.get("preferred_unit") or "")
    preferred_unit = normalize_text(preferred_unit_raw)
    raw_value = str(relation.get("value_text") or "")
    missing_value = is_missing_value_text(raw_value)
    # A plain substring/containment check here would let a field whose unit is
    # a prefix of another field's compound unit (e.g. "ml" vs "ml/m2") falsely
    # match a value carrying the *other* unit, since ``normalize_text`` turns
    # "/" into whitespace and erases the distinction entirely. Comparing each
    # value's own trailing unit text against the field's unit, with "/" kept
    # intact, requires them to actually be the same unit.
    unit_match = bool(preferred_unit_raw) and _normalize_unit(preferred_unit_raw) == _normalize_unit(
        _value_unit_suffix(raw_value)
    )

    unit_bonus = 0.10 if unit_match else 0.0
    table_bonus = 0.10 if str(relation.get("relation_type") or "").startswith("table_") else 0.0
    base_score = 0.74 * label_score + 0.12 * max(-1.0, context_value) + unit_bonus + table_bonus

    if exact_alias:
        if unit_match:
            base_score = max(base_score, 0.93)
        elif missing_value or not preferred_unit:
            base_score = max(base_score, 0.90)
        else:
            base_score = max(base_score, 0.82)

    relation_confidence = max(0.0, min(1.0, float(relation.get("confidence") or 0.0)))
    score = base_score * (0.76 + 0.24 * relation_confidence) * max(0.0, float(feedback_multiplier))
    score = max(0.0, min(1.0, score))
    return score, {
        "label_score": round(label_score, 4),
        "exact_alias": exact_alias,
        "unit_match": unit_match,
        "missing_value": missing_value,
        "context_score": round(context_value, 4),
    }
