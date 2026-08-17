from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config import FieldSpec, Profile
from .dynamic_locator import normalize_for_matching

MODEL_VERSION = 1


def canonical_screen_label(field: FieldSpec) -> str:
    """Return the human-readable row header used as normalization target."""
    if field.screen_labels:
        return str(field.screen_labels[0])
    return field.label


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_header_normalization_model(
    rows: Iterable[dict[str, Any]],
    profile: Profile,
    destination: str | Path,
) -> dict[str, Any]:
    """Compile reviewed noisy row headers into a deterministic alias model.

    The model does not change OCR transcripts. It learns that a raw locator
    reading, for example ``ED VoIume``, belongs to a configured canonical row.
    Aliases that point to multiple fields inside the same panel are excluded to
    prevent an exact learned alias from making the locator ambiguous.
    """
    fields = {field.key: field for field in profile.fields}
    accepted: list[dict[str, Any]] = []
    ignored = 0
    for raw in rows:
        row = dict(raw)
        if str(row.get("header_review_status") or "") != "accepted":
            continue
        observed = str(row.get("locator_label_text") or "").strip()
        target = str(row.get("header_target_field_key") or row.get("field_key") or "").strip()
        if not observed or target not in fields:
            ignored += 1
            continue
        normalized = normalize_for_matching(observed)
        if not normalized:
            ignored += 1
            continue
        accepted.append(
            {
                "sample_id": str(row.get("sample_id") or ""),
                "observed": observed,
                "normalized": normalized,
                "target_field_key": target,
                "panel": fields[target].panel,
                "canonical_label": canonical_screen_label(fields[target]),
                "corrected_label": str(row.get("header_exact_label") or "").strip(),
            }
        )

    # Detect ambiguous mappings per panel. The same label is intentionally
    # allowed in LV and RV because the locator already limits candidates to a
    # panel before matching.
    assignments: dict[tuple[str | None, str], set[str]] = defaultdict(set)
    for item in accepted:
        assignments[(item["panel"], item["normalized"])].add(item["target_field_key"])

    conflict_keys = {key for key, targets in assignments.items() if len(targets) > 1}
    conflicts = [
        {
            "panel": panel,
            "normalized": normalized,
            "target_field_keys": sorted(assignments[(panel, normalized)]),
        }
        for panel, normalized in sorted(conflict_keys, key=lambda value: (str(value[0]), value[1]))
    ]

    configured_aliases = {
        field.key: {
            normalize_for_matching(value)
            for value in (field.screen_labels or (canonical_screen_label(field),))
            if normalize_for_matching(value)
        }
        for field in profile.fields
    }
    per_field: dict[str, Counter[str]] = defaultdict(Counter)
    display_text: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    included_examples = 0
    for item in accepted:
        key = (item["panel"], item["normalized"])
        if key not in conflict_keys:
            target = item["target_field_key"]
            normalized = item["normalized"]
            if normalized not in configured_aliases.get(target, set()):
                per_field[target][normalized] += 1
                display_text[(target, normalized)][item["observed"]] += 1
            included_examples += 1

        # The human correction is also a valid alias. This supports legitimate
        # label variants that are not yet present in the profile while keeping
        # the noisy OCR reading available as the actual training example.
        corrected = str(item.get("corrected_label") or "").strip()
        corrected_normalized = normalize_for_matching(corrected)
        if corrected_normalized:
            corrected_key = (item["panel"], corrected_normalized)
            corrected_targets = assignments.get(corrected_key, {item["target_field_key"]})
            if len(corrected_targets) == 1:
                target = item["target_field_key"]
                if corrected_normalized not in configured_aliases.get(target, set()):
                    per_field[target][corrected_normalized] += 1
                    display_text[(target, corrected_normalized)][corrected] += 1

    field_aliases: dict[str, list[dict[str, Any]]] = {}
    for field in profile.fields:
        aliases: list[dict[str, Any]] = []
        for normalized, count in per_field.get(field.key, Counter()).most_common():
            observed = display_text[(field.key, normalized)].most_common(1)[0][0]
            aliases.append(
                {
                    "text": observed,
                    "normalized": normalized,
                    "count": count,
                }
            )
        if aliases:
            field_aliases[field.key] = aliases

    payload = {
        "model_type": "row-header-alias-normalizer",
        "model_version": MODEL_VERSION,
        "generated_at": _utcnow(),
        "profile": profile.name,
        "accepted_review_count": len(accepted),
        "included_example_count": included_examples,
        "ignored_review_count": ignored,
        "learned_alias_count": sum(len(items) for items in field_aliases.values()),
        "field_aliases": field_aliases,
        "conflicts": conflicts,
    }
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
    return payload


def load_header_aliases(
    path: str | Path,
    profile: Profile,
) -> dict[str, tuple[str, ...]]:
    """Load learned aliases, ignoring stale or malformed model files safely."""
    model_path = Path(path)
    try:
        payload = json.loads(model_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("model_type") != "row-header-alias-normalizer":
        return {}
    if int(payload.get("model_version") or 0) != MODEL_VERSION:
        return {}
    if str(payload.get("profile") or "") != profile.name:
        return {}

    valid_fields = {field.key for field in profile.fields}
    result: dict[str, tuple[str, ...]] = {}
    raw_aliases = payload.get("field_aliases")
    if not isinstance(raw_aliases, dict):
        return {}
    for field_key, aliases in raw_aliases.items():
        if field_key not in valid_fields or not isinstance(aliases, list):
            continue
        texts: list[str] = []
        seen: set[str] = set()
        for item in aliases:
            text = str(item.get("text") if isinstance(item, dict) else item).strip()
            normalized = normalize_for_matching(text)
            if text and normalized and normalized not in seen:
                seen.add(normalized)
                texts.append(text)
        if texts:
            result[field_key] = tuple(texts)
    return result
