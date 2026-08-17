from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Iterable

VALID_RELATION_FEEDBACK_VERDICTS = {"accepted", "rejected"}
RELATION_FEEDBACK_REASONS: dict[str, str] = {
    "multi_row_label": "Label bevat meerdere rijen/velden",
    "wrong_pair": "Verkeerd label aan deze waarde gekoppeld",
    "wrong_value": "Verkeerde waarde bij dit label gekozen",
    "wrong_table_structure": "Tabelrij of -kolom verkeerd geïnterpreteerd",
    "bad_geometry": "ROI/geometrie is onjuist",
    "irrelevant": "Geen relevant uitvoerveld",
    "duplicate": "Dubbele/overbodige detectie",
    "other": "Andere reden",
}

_NUMBER_RE = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def normalize_feedback_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("²", "2")
    text = re.sub(r"[^a-z0-9%/+*.-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def value_shape(value: str) -> str:
    normalized = normalize_feedback_text(value)
    normalized = _NUMBER_RE.sub("<n>", normalized)
    return re.sub(r"(?:<n>\s*)+", "<n> ", normalized).strip()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bucket(value: float, step: float, *, minimum: float = -10.0, maximum: float = 10.0) -> float:
    value = min(maximum, max(minimum, value))
    return round(value / step) * step


def relation_snapshot(relation: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    source_width = max(1, _safe_int(source.get("image_width"), 1))
    source_height = max(1, _safe_int(source.get("image_height"), 1))

    lx1 = _safe_int(relation.get("label_x1"))
    ly1 = _safe_int(relation.get("label_y1"))
    lx2 = _safe_int(relation.get("label_x2"))
    ly2 = _safe_int(relation.get("label_y2"))
    vx1 = _safe_int(relation.get("value_x1"))
    vy1 = _safe_int(relation.get("value_y1"))
    vx2 = _safe_int(relation.get("value_x2"))
    vy2 = _safe_int(relation.get("value_y2"))

    label_width = max(1, lx2 - lx1)
    label_height = max(1, ly2 - ly1)
    value_width = max(1, vx2 - vx1)
    value_height = max(1, vy2 - vy1)
    label_center_y = (ly1 + ly2) / 2.0
    value_center_y = (vy1 + vy2) / 2.0
    vertical_delta_ratio = abs(label_center_y - value_center_y) / max(label_height, value_height, 1)
    horizontal_gap_ratio = (vx1 - lx2) / source_width if lx2 > lx1 else 0.0
    label_height_ratio = label_height / max(value_height, 1)
    label_width_ratio = label_width / source_width
    value_width_ratio = value_width / source_width

    label_text = str(relation.get("label_text") or "")
    value_text = str(relation.get("value_text") or "")
    context_text = str(relation.get("context_text") or relation.get("relation_context") or "")
    normalized_label = normalize_feedback_text(label_text)
    normalized_context = value_shape(context_text)

    return {
        "relation_id": str(relation.get("relation_id") or ""),
        "source_id": str(relation.get("source_id") or source.get("source_id") or ""),
        "label_text": label_text,
        "value_text": value_text,
        "label_normalized": normalized_label,
        "value_shape": value_shape(value_text),
        "context_shape": normalized_context,
        "relation_type": str(relation.get("relation_type") or ""),
        "rank": max(1, _safe_int(relation.get("rank"), 1)),
        "table_id": str(relation.get("table_id") or ""),
        "row_index": _safe_int(relation.get("row_index"), -1),
        "value_column_index": _safe_int(relation.get("value_column_index"), -1),
        "confidence": max(0.0, min(1.0, _safe_float(relation.get("confidence")))),
        "label_height_ratio": label_height_ratio,
        "vertical_delta_ratio": vertical_delta_ratio,
        "horizontal_gap_ratio": horizontal_gap_ratio,
        "label_width_ratio": label_width_ratio,
        "value_width_ratio": value_width_ratio,
        "label_word_count": len(normalized_label.split()),
        "source_width": source_width,
        "source_height": source_height,
        "label_box": [lx1, ly1, lx2, ly2],
        "value_box": [vx1, vy1, vx2, vy2],
    }


def relation_signature(snapshot: dict[str, Any]) -> str:
    # Deliberately use geometry buckets and value shape rather than literal values.
    # This survives small OCR/box shifts and generalises 71.5 ml -> 68.2 ml while
    # still keeping left/right panel context and merged-label text distinct.
    payload = "|".join(
        [
            str(snapshot.get("label_normalized") or ""),
            str(snapshot.get("value_shape") or ""),
            str(snapshot.get("context_shape") or ""),
            str(snapshot.get("relation_type") or ""),
            str(1 if _safe_int(snapshot.get("rank"), 1) == 1 else 2),
            f"h{_bucket(_safe_float(snapshot.get('label_height_ratio'), 1.0), 0.25, minimum=0, maximum=5):.2f}",
            f"v{_bucket(_safe_float(snapshot.get('vertical_delta_ratio')), 0.20, minimum=0, maximum=5):.2f}",
            f"g{_bucket(_safe_float(snapshot.get('horizontal_gap_ratio')), 0.02, minimum=-0.25, maximum=0.75):.2f}",
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _text_similarity(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.82 + 0.18 * min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


def feedback_similarity(
    current: dict[str, Any], example: dict[str, Any], reason_code: str = ""
) -> float:
    label = _text_similarity(
        str(current.get("label_normalized") or ""),
        str(example.get("label_normalized") or ""),
    )
    context = _text_similarity(
        str(current.get("context_shape") or ""),
        str(example.get("context_shape") or ""),
    )
    value = _text_similarity(
        str(current.get("value_shape") or ""),
        str(example.get("value_shape") or ""),
    )
    relation_type = 1.0 if str(current.get("relation_type") or "") == str(example.get("relation_type") or "") else 0.0
    rank = 1.0 if (int(current.get("rank") or 1) == 1) == (int(example.get("rank") or 1) == 1) else 0.0
    table_structure = relation_type
    if relation_type and str(current.get("relation_type") or "") == "table_cell":
        row_delta = abs(int(current.get("row_index") or -1) - int(example.get("row_index") or -1))
        col_delta = abs(int(current.get("value_column_index") or -1) - int(example.get("value_column_index") or -1))
        table_structure = math.exp(-(row_delta * 0.10 + col_delta * 0.55))

    geometry_delta = (
        abs(_safe_float(current.get("label_height_ratio"), 1) - _safe_float(example.get("label_height_ratio"), 1)) / 3.0
        + abs(_safe_float(current.get("vertical_delta_ratio")) - _safe_float(example.get("vertical_delta_ratio"))) / 2.0
        + abs(_safe_float(current.get("horizontal_gap_ratio")) - _safe_float(example.get("horizontal_gap_ratio"))) / 0.25
    ) / 3.0
    geometry = math.exp(-max(0.0, geometry_delta))

    # The rejection reason tells the learner which features are meaningful. A
    # merged-label rejection should generalise mostly by label/geometry, while a
    # table-structure rejection should care more about row/column structure.
    weights = {
        "multi_row_label": (0.46, 0.10, 0.02, 0.07, 0.02, 0.33),
        "wrong_pair": (0.30, 0.13, 0.10, 0.08, 0.04, 0.35),
        "wrong_value": (0.34, 0.13, 0.24, 0.08, 0.04, 0.17),
        "wrong_table_structure": (0.25, 0.10, 0.06, 0.28, 0.03, 0.28),
        "bad_geometry": (0.18, 0.08, 0.03, 0.08, 0.03, 0.60),
        "irrelevant": (0.56, 0.20, 0.05, 0.07, 0.02, 0.10),
        "duplicate": (0.34, 0.08, 0.22, 0.12, 0.03, 0.21),
    }.get(reason_code, (0.42, 0.14, 0.10, 0.10, 0.05, 0.19))
    relation_component = table_structure if reason_code == "wrong_table_structure" else relation_type
    score = (
        weights[0] * label
        + weights[1] * context
        + weights[2] * value
        + weights[3] * relation_component
        + weights[4] * rank
        + weights[5] * geometry
    )
    return max(0.0, min(1.0, score))


def evaluate_feedback(
    snapshot: dict[str, Any],
    examples: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Memory-based relation-quality learner.

    Confirmed relations are positive examples and explicit rejections are negative
    examples. One exact rejection suppresses the same pattern immediately. Similar
    patterns influence confidence, but require repeated negative evidence before
    they are hard-suppressed. This keeps the feedback useful with very little data
    without pretending that PaddleOCR itself has been retrained.
    """
    signature = relation_signature(snapshot)
    positive_weight = 0.0
    negative_weight = 0.0
    strongest_negative = 0.0
    strongest_positive = 0.0
    matched = 0
    exact_reject = False
    reasons: list[str] = []

    for example in examples:
        if not bool(example.get("active", 1)):
            continue
        verdict = str(example.get("verdict") or "")
        example_snapshot = example.get("snapshot") or {}
        if not isinstance(example_snapshot, dict):
            continue
        example_signature = str(example.get("relation_signature") or "")
        similarity = 1.0 if example_signature == signature else feedback_similarity(snapshot, example_snapshot, str(example.get("reason_code") or ""))
        if similarity < 0.68:
            continue
        matched += 1
        weight = similarity ** 3
        if verdict == "rejected":
            negative_weight += weight
            strongest_negative = max(strongest_negative, similarity)
            reason_code = str(example.get("reason_code") or "")
            if reason_code and reason_code not in reasons:
                reasons.append(reason_code)
            if example_signature == signature:
                exact_reject = True
        elif verdict == "accepted":
            positive_weight += weight
            strongest_positive = max(strongest_positive, similarity)

    # Laplace prior keeps one isolated example from overcorrecting unrelated data.
    quality = (1.0 + positive_weight) / (2.0 + positive_weight + negative_weight)
    multiplier = max(0.45, min(1.18, 0.62 + 0.76 * quality))
    hard_reject = exact_reject
    if not hard_reject and negative_weight >= 1.55 and negative_weight > positive_weight * 1.8 and strongest_negative >= 0.92:
        hard_reject = True

    return {
        "signature": signature,
        "quality": quality,
        "multiplier": multiplier,
        "hard_reject": hard_reject,
        "matched_examples": matched,
        "positive_weight": positive_weight,
        "negative_weight": negative_weight,
        "strongest_negative": strongest_negative,
        "strongest_positive": strongest_positive,
        "reason_codes": reasons,
    }
