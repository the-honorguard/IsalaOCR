from __future__ import annotations

from typing import Any, Callable

from ..training.generic_detection import normalize_text

MISSING_VALUE_MARKERS = ("-", "–", "—")


def is_missing_value_text(value: object) -> bool:
    """Return True only for explicit empty-value markers, never negatives."""
    return str(value or "").strip() in MISSING_VALUE_MARKERS


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
    preferred_unit = normalize_text(str(field.get("preferred_unit") or ""))
    raw_value = str(relation.get("value_text") or "")
    normalized_value = normalize_text(raw_value)
    missing_value = is_missing_value_text(raw_value)
    unit_match = bool(preferred_unit and preferred_unit in normalized_value)

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
