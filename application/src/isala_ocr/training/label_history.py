"""Learn which functional field a label text usually maps to, from mapping history.

Mapping Studio (``routes_mapping_studio.py``) asks an operator to pick a
functional field for every label on every source, even though most labels
("Ejection Fraction", "ED Volume", ...) are the exact same handful of strings
on nearly every CMR report. This aggregates the project's own confirmed
mapping history (``TrainingDatabase.label_history_field_counts()``) into
"this label has always meant this field, N times" so Mapping Studio can
pre-select that field instead of making an operator repeat the same choice on
every source. See ``suggest_family_for_label`` for the safety rule.
"""

from __future__ import annotations

from typing import Any, Callable

from .generic_detection import normalize_text

# How many sources must already have confirmed a label -> field pairing
# before it is trusted enough to pre-select automatically. Chosen to require
# a real pattern (an operator's repeated, deliberate choice) rather than a
# single click that happened to be wrong; the pre-selected field is always a
# suggestion an operator still reviews and explicitly saves, never applied
# silently.
MINIMUM_SOURCES_FOR_AUTO_SUGGESTION = 5


def label_family_history(
    history_rows: list[dict[str, Any]],
    fields: list[dict[str, Any]],
    *,
    field_family: Callable[[dict[str, Any]], str],
) -> dict[str, dict[str, int]]:
    """Aggregate raw ``(label_text, field_key, source_count)`` rows into
    ``{normalized_label: {family: source_count}}``.

    Grouped by lateral-agnostic family (e.g. ``lv_ed_volume`` and
    ``rv_ed_volume`` both become ``ed_volume``) because Mapping Studio's
    dropdown itself only offers the family; the actual left/right field is
    resolved from the relation's own table/panel at save time.
    """
    family_by_field_key = {
        str(field.get("field_key") or ""): (field_family(field) or str(field.get("field_key") or ""))
        for field in fields
    }
    result: dict[str, dict[str, int]] = {}
    for row in history_rows:
        family = family_by_field_key.get(str(row.get("field_key") or ""))
        if not family:
            continue
        label = normalize_text(str(row.get("label_text") or ""))
        if not label:
            continue
        count = int(row.get("source_count") or 0)
        if count <= 0:
            continue
        bucket = result.setdefault(label, {})
        bucket[family] = bucket.get(family, 0) + count
    return result


def suggest_family_for_label(
    label_text: str,
    history: dict[str, dict[str, int]],
    *,
    minimum_sources: int = MINIMUM_SOURCES_FOR_AUTO_SUGGESTION,
) -> tuple[str, int] | None:
    """The one family this label has ever been confirmed against, if any.

    Requires a *single* family with enough confirmations, not merely the most
    common one: a label that has ever been mapped two different ways is a
    sign that its correct field depends on context this history does not
    capture (a merged/ambiguous OCR label, a panel-specific quirk, ...), so
    those keep requiring a manual pick instead of risking a wrong guess.
    """
    label = normalize_text(label_text)
    if not label:
        return None
    counts = history.get(label)
    if not counts or len(counts) != 1:
        return None
    ((family, count),) = counts.items()
    if count < minimum_sources:
        return None
    return family, count
