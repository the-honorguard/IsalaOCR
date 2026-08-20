from __future__ import annotations

import re
from typing import Any, Iterable

from ..training.generic_detection import normalize_text

_LEFT_TERMS = {
    "left", "linker", "linkerventrikel", "lv", "lvef", "lvsv", "lvedv", "lvesv", "lvco",
}
_RIGHT_TERMS = {
    "right", "rechter", "rechterventrikel", "rv", "rvef", "rvsv", "rvedv", "rvesv", "rvco",
}
_LEFT_PHRASES = ("left ventricle", "linker ventrikel")
_RIGHT_PHRASES = ("right ventricle", "rechter ventrikel")


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text(value)))


def field_lateral_side(field: dict[str, Any]) -> str:
    key = str(field.get("field_key") or "").casefold()
    if key.startswith("lv_"):
        return "left"
    if key.startswith("rv_"):
        return "right"

    group = normalize_text(str(field.get("group_name") or ""))
    tokens = _tokens(group)
    left = bool(tokens & _LEFT_TERMS) or any(phrase in group for phrase in _LEFT_PHRASES)
    right = bool(tokens & _RIGHT_TERMS) or any(phrase in group for phrase in _RIGHT_PHRASES)
    if left == right:
        return ""
    return "left" if left else "right"


def field_lateral_suffix(field: dict[str, Any]) -> str:
    key = str(field.get("field_key") or "").casefold()
    if key.startswith("lv_") or key.startswith("rv_"):
        return key[3:]
    return ""


def ambiguous_lateral_suffixes(fields: Iterable[dict[str, Any]]) -> set[str]:
    sides_by_suffix: dict[str, set[str]] = {}
    for field in fields:
        suffix = field_lateral_suffix(field)
        side = field_lateral_side(field)
        if not suffix or not side:
            continue
        sides_by_suffix.setdefault(suffix, set()).add(side)
    return {
        suffix
        for suffix, sides in sides_by_suffix.items()
        if "left" in sides and "right" in sides
    }


def relation_lateral_side(relation: dict[str, Any]) -> str:
    """Read explicit left/right evidence from application-level metadata."""
    parts = [
        relation.get("label_text"), relation.get("context_text"), relation.get("panel_name"),
        relation.get("panel_label"), relation.get("table_name"), relation.get("table_label"),
        relation.get("column_header"), relation.get("header_text"),
    ]
    text = normalize_text(" ".join(str(part or "") for part in parts))
    tokens = _tokens(text)
    left = bool(tokens & _LEFT_TERMS) or any(phrase in text for phrase in _LEFT_PHRASES)
    right = bool(tokens & _RIGHT_TERMS) or any(phrase in text for phrase in _RIGHT_PHRASES)
    if left and right:
        return "ambiguous"
    if left:
        return "left"
    if right:
        return "right"
    return ""


def lateral_candidate_allowed(
    field: dict[str, Any],
    relation: dict[str, Any],
    ambiguous_suffixes: set[str],
) -> bool:
    """Avoid arbitrary bilateral application-field assignments on score ties."""
    suffix = field_lateral_suffix(field)
    side = field_lateral_side(field)
    if not suffix or not side or suffix not in ambiguous_suffixes:
        return True
    return relation_lateral_side(relation) == side
