from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

from rapidfuzz.distance import Levenshtein


def _confusions(expected: str, observed: str) -> Counter[str]:
    result: Counter[str] = Counter()
    matcher = SequenceMatcher(a=expected, b=observed, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        left = expected[i1:i2]
        right = observed[j1:j2]
        if tag == "replace" and len(left) == len(right):
            for source, target in zip(left, right, strict=True):
                result[f"{source!r}→{target!r}"] += 1
        elif tag == "delete":
            for source in left:
                result[f"{source!r}→∅"] += 1
        elif tag == "insert":
            for target in right:
                result[f"∅→{target!r}"] += 1
        else:
            result[f"{left!r}→{right!r}"] += 1
    return result


def compute_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    exact = 0
    distance = 0
    characters = 0
    confusion_counts: Counter[str] = Counter()
    per_field_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        expected = str(record["expected"])
        observed = str(record.get("observed", ""))
        field = str(record.get("field_key", "unknown"))
        is_exact = expected == observed
        exact += int(is_exact)
        edit_distance = int(Levenshtein.distance(expected, observed))
        distance += edit_distance
        characters += len(expected)
        confusion_counts.update(_confusions(expected, observed))
        per_field_records[field].append(
            {**record, "exact": is_exact, "edit_distance": edit_distance}
        )

    per_field = {}
    for field, items in sorted(per_field_records.items()):
        field_chars = sum(len(str(item["expected"])) for item in items)
        field_distance = sum(int(item["edit_distance"]) for item in items)
        field_exact = sum(bool(item["exact"]) for item in items)
        per_field[field] = {
            "samples": len(items),
            "exact_match_accuracy": field_exact / len(items),
            "character_error_rate": field_distance / max(field_chars, 1),
        }

    return {
        "samples": total,
        "exact_matches": exact,
        "exact_match_accuracy": exact / total if total else 0.0,
        "total_edit_distance": distance,
        "expected_characters": characters,
        "character_error_rate": distance / max(characters, 1),
        "per_field": per_field,
        "confusion_pairs": [
            {"pair": pair, "count": count}
            for pair, count in confusion_counts.most_common(50)
        ],
    }
