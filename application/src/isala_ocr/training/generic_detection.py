from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from ..models import Box, OCRToken

GENERIC_DETECTOR_VERSION = "generic-layout-v3-table-aware"

_UNIT_PATTERN = (
    r"(?:m[lL]/(?:min|m[²2])|g(?:r)?/m[²2]|[lL]/\(?min(?:[·*/]m[²2])?\)?|"
    r"bpm|kg|mg|mm|cm|m[lL]|m[²2]|%|g(?:r)?|m|[lL]|min)"
)
_NUMBER_RE = re.compile(
    rf"(?<![A-Za-z0-9])[-+]?\d+(?:[.,]\d+)?(?:\s*{_UNIT_PATTERN})?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_SHORT_ENUMS = {"m", "f", "male", "female", "ja", "nee", "yes", "no", "true", "false"}
_UNIT_RE = re.compile(rf"^{_UNIT_PATTERN}$", re.IGNORECASE)
_LABEL_HINT_RE = re.compile(r"[A-Za-zÀ-ÿ]", re.UNICODE)


@dataclass(frozen=True)
class DetectedLine:
    index: int
    tokens: tuple[OCRToken, ...]
    box: Box
    text: str
    confidence: float

    @property
    def center_y(self) -> float:
        return (self.box.y1 + self.box.y2) / 2.0


@dataclass(frozen=True)
class GenericBlock:
    block_id: str
    source_id: str
    block_type: str
    role: str
    text: str
    normalized_text: str
    confidence: float
    box: Box
    line_index: int
    sequence_index: int
    parent_block_id: str | None = None
    context_text: str = ""
    table_id: str = ""
    row_index: int = -1
    column_index: int = -1
    row_span: int = 1
    column_span: int = 1
    geometry_source: str = "ocr"

    def as_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "source_id": self.source_id,
            "block_type": self.block_type,
            "role": self.role,
            "text": self.text,
            "normalized_text": self.normalized_text,
            "confidence": float(self.confidence),
            "x1": self.box.x1,
            "y1": self.box.y1,
            "x2": self.box.x2,
            "y2": self.box.y2,
            "line_index": self.line_index,
            "sequence_index": self.sequence_index,
            "parent_block_id": self.parent_block_id or "",
            "context_text": self.context_text,
            "table_id": self.table_id,
            "row_index": int(self.row_index),
            "column_index": int(self.column_index),
            "row_span": int(self.row_span),
            "column_span": int(self.column_span),
            "geometry_source": self.geometry_source,
        }


@dataclass(frozen=True)
class GenericRelation:
    relation_id: str
    source_id: str
    label_block_id: str | None
    value_block_id: str
    unit_block_id: str | None
    relation_type: str
    confidence: float
    rank: int
    context_text: str
    table_id: str = ""
    row_index: int = -1
    value_column_index: int = -1

    def as_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "label_block_id": self.label_block_id or "",
            "value_block_id": self.value_block_id,
            "unit_block_id": self.unit_block_id or "",
            "relation_type": self.relation_type,
            "confidence": float(self.confidence),
            "rank": int(self.rank),
            "context_text": self.context_text,
            "table_id": self.table_id,
            "row_index": int(self.row_index),
            "value_column_index": int(self.value_column_index),
        }


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("²", "2")
    text = re.sub(r"[^a-z0-9%]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _union(boxes: Iterable[Box]) -> Box:
    values = list(boxes)
    if not values:
        raise ValueError("Cannot union an empty box sequence")
    return Box(
        min(box.x1 for box in values),
        min(box.y1 for box in values),
        max(box.x2 for box in values),
        max(box.y2 for box in values),
    )


def _weighted_confidence(tokens: Sequence[OCRToken]) -> float:
    if not tokens:
        return 0.0
    weights = [max(1, len(token.text.strip())) for token in tokens]
    return sum(float(token.confidence) * weight for token, weight in zip(tokens, weights, strict=True)) / sum(weights)


def _center_y(box: Box) -> float:
    return (box.y1 + box.y2) / 2.0


def _center_x(box: Box) -> float:
    return (box.x1 + box.x2) / 2.0


def _vertical_overlap_ratio(left: Box, right: Box) -> float:
    overlap = max(0, min(left.y2, right.y2) - max(left.y1, right.y1))
    return overlap / max(1, min(left.height, right.height))


def _line_group_score(group: Sequence[OCRToken], token: OCRToken) -> float | None:
    """Return an alignment score when *token* belongs to an existing text row.

    OCR boxes on result screens are often only a few pixels apart vertically.
    The previous implementation compared a token with the *union* of a group and
    used a 65% height tolerance. Once two neighbouring rows were accidentally
    joined, the union grew and made the next accidental join even easier. That
    produced multi-row labels and enormous semantic rectangles.

    This version compares against the median row geometry and deliberately uses a
    much tighter vertical tolerance.
    """
    if token.box is None or not group:
        return None
    boxes = [item.box for item in group if item.box is not None]
    if not boxes:
        return None
    centers = sorted(_center_y(box) for box in boxes)
    heights = sorted(max(1, box.height) for box in boxes)
    center = centers[len(centers) // 2]
    median_height = heights[len(heights) // 2]
    token_height = max(1, token.box.height)
    distance = abs(_center_y(token.box) - center)
    overlap = max((_vertical_overlap_ratio(box, token.box) for box in boxes), default=0.0)
    tolerance = max(2.0, 0.38 * max(median_height, token_height))
    # Very different heights usually mean a title/annotation and a table row that
    # happen to share a baseline, not one semantic row.
    height_ratio = max(median_height, token_height) / max(1, min(median_height, token_height))
    if height_ratio > 3.0:
        return None
    if overlap < 0.52 and distance > tolerance:
        return None
    return distance - overlap * max(median_height, token_height)


def group_tokens_into_lines(tokens: Sequence[OCRToken]) -> list[DetectedLine]:
    usable = [token for token in tokens if token.box is not None and token.text.strip()]
    usable.sort(key=lambda token: (_center_y(token.box), token.box.x1))
    groups: list[list[OCRToken]] = []
    for token in usable:
        selected: list[OCRToken] | None = None
        best_score = float("inf")
        for group in groups:
            score = _line_group_score(group, token)
            if score is not None and score < best_score:
                selected = group
                best_score = score
        if selected is None:
            groups.append([token])
        else:
            selected.append(token)

    lines: list[DetectedLine] = []
    for group in groups:
        ordered = tuple(sorted(group, key=lambda token: token.box.x1 if token.box else 0))
        box = _union(token.box for token in ordered if token.box is not None)
        text = " ".join(token.text.strip() for token in ordered if token.text.strip())
        lines.append(
            DetectedLine(
                index=0,
                tokens=ordered,
                box=box,
                text=text,
                confidence=_weighted_confidence(ordered),
            )
        )
    lines.sort(key=lambda line: (line.center_y, line.box.x1))
    return [
        DetectedLine(
            index=index,
            tokens=line.tokens,
            box=line.box,
            text=line.text,
            confidence=line.confidence,
        )
        for index, line in enumerate(lines)
    ]


def _contiguous_label_groups(parts: Sequence[GenericBlock]) -> list[list[GenericBlock]]:
    """Group only genuinely adjacent, consecutive label fragments.

    Values and units are hard boundaries. This is important for compact rows such
    as ``HR: 92 bpm  BSA: 2.13 m²``: HR and BSA must never be merged merely
    because their x-coordinates are close.
    """
    ordered = sorted(parts, key=lambda item: (item.box.x1, item.sequence_index))
    groups: list[list[GenericBlock]] = []
    current: list[GenericBlock] = []
    for part in ordered:
        if part.role not in {"label", "unknown"}:
            if current:
                groups.append(current)
                current = []
            continue
        if not current:
            current = [part]
            continue
        previous = current[-1]
        gap = part.box.x1 - previous.box.x2
        local_height = max(1, previous.box.height, part.box.height)
        overlap = _vertical_overlap_ratio(previous.box, part.box)
        # Normal inter-word whitespace is usually below one text height. Keep a
        # small absolute floor for low-resolution DICOM screenshots.
        max_gap = max(10, int(round(local_height * 1.25)))
        if gap <= max_gap and overlap >= 0.45:
            current.append(part)
        else:
            groups.append(current)
            current = [part]
    if current:
        groups.append(current)
    return groups


def _semantic_label_from_group(
    source_id: str,
    line_id: str,
    line_index: int,
    context: str,
    group: Sequence[GenericBlock],
    suffix: str,
    *,
    role: str = "label",
) -> GenericBlock:
    box = _union(part.box for part in group)
    text = " ".join(part.text for part in group).strip()
    return GenericBlock(
        block_id=_stable_id(source_id, f"row_{role}", box, text, suffix),
        source_id=source_id, block_type="semantic", role=role,
        text=text, normalized_text=normalize_text(text),
        confidence=sum(part.confidence for part in group) / max(1, len(group)),
        box=box, line_index=line_index, sequence_index=min(part.sequence_index for part in group),
        parent_block_id=line_id, context_text=context,
    )

def looks_like_value(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    normalized = normalize_text(stripped)
    if normalized in _SHORT_ENUMS:
        return True
    if stripped in {"-", "–", "—"}:
        return True
    match = _NUMBER_RE.search(stripped)
    if match is None:
        return False
    # Dates and long identifiers remain candidates, but very long prose with one
    # number is treated as a line/header rather than a value token.
    alpha_count = sum(ch.isalpha() for ch in stripped)
    digit_count = sum(ch.isdigit() for ch in stripped)
    return digit_count > 0 and (alpha_count <= 8 or digit_count >= alpha_count)


def looks_like_unit(text: str) -> bool:
    return bool(_UNIT_RE.fullmatch(str(text or "").strip()))


def looks_like_label(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped or looks_like_value(stripped) or looks_like_unit(stripped):
        return False
    alpha_count = sum(ch.isalpha() for ch in stripped)
    return alpha_count >= 2 and bool(_LABEL_HINT_RE.search(stripped))


def _stable_id(source_id: str, kind: str, box: Box, text: str, suffix: str = "") -> str:
    payload = f"{source_id}|{kind}|{box.x1},{box.y1},{box.x2},{box.y2}|{text}|{suffix}"
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]


def _subbox(box: Box, text: str, start: int, end: int) -> Box:
    """Estimate a sub-box for semantic text embedded in one OCR token.

    PaddleOCR sometimes returns an entire key/value strip as one token. Exact
    character geometry is unavailable in that case, so proportional horizontal
    geometry is used. The original token and its unmodified box remain stored as
    the source of truth.
    """
    length = max(1, len(text))
    left = box.x1 + int(round(box.width * max(0, start) / length))
    right = box.x1 + int(round(box.width * min(length, max(start + 1, end)) / length))
    return Box(left, box.y1, max(left + 1, right), box.y2)


def _clean_label_span(prefix: str, absolute_start: int) -> tuple[str, int, int] | None:
    """Return the last key-like part before a value and its character span."""
    if not prefix.strip():
        return None
    # A colon is the strongest generic key/value signal. For strings such as
    # ``Study info: HR:`` the final segment (HR) is the actual field label.
    colon_parts = list(re.finditer(r"([^:;|]+)\s*:\s*", prefix))
    if colon_parts:
        match = colon_parts[-1]
        candidate = match.group(1)
        local_start = match.start(1)
    else:
        candidate = prefix
        local_start = 0
    # Remove table punctuation and parenthetical context before the actual key.
    if ")" in candidate:
        offset = candidate.rfind(")") + 1
        local_start += offset
        candidate = candidate[offset:]
    stripped = candidate.strip(" \t-–—|;,.()[]")
    if not stripped or not looks_like_label(stripped):
        return None
    relative = candidate.find(stripped)
    start = absolute_start + local_start + max(0, relative)
    return stripped, start, start + len(stripped)


def _split_token_parts(block: GenericBlock) -> list[GenericBlock]:
    """Split combined OCR tokens into approximate label/value parts.

    This handles compact strips such as ``HR: 92 bpm BSA: 2.13 m²`` while
    preserving the raw token separately. Pure label or pure value tokens are
    returned unchanged.
    """
    text = block.text
    matches = list(_NUMBER_RE.finditer(text))
    if not matches:
        enum = re.search(
            r"(?P<label>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 /+._-]{1,80})\s*:\s*"
            r"(?P<value>M|F|Male|Female|Yes|No|Ja|Nee|True|False)\s*$",
            text, re.IGNORECASE,
        )
        if enum is None:
            label_span = _clean_label_span(text, 0)
            if label_span is None:
                return [block]
            label_text, label_start, label_end = label_span
            # Keep ordinary atomic labels as their original token. Only derive a
            # smaller label when punctuation/context obscures the actual key.
            if normalize_text(label_text) == normalize_text(text) and label_text == text.strip():
                return [block]
            label_box = _subbox(block.box, text, label_start, label_end)
            return [
                GenericBlock(
                    block_id=_stable_id(block.source_id, "token_part_label", label_box, label_text, block.block_id),
                    source_id=block.source_id, block_type="part", role="label",
                    text=label_text, normalized_text=normalize_text(label_text),
                    confidence=block.confidence, box=label_box, line_index=block.line_index,
                    sequence_index=block.sequence_index * 100, parent_block_id=block.block_id,
                    context_text=block.context_text,
                )
            ]
        matches = [enum]

    parts: list[GenericBlock] = []
    cursor = 0
    for index, match in enumerate(matches, start=1):
        if "value" in match.re.groupindex:
            value_start, value_end = match.span("value")
            value_text = match.group("value")
            label_match = (match.group("label"), match.start("label"), match.end("label"))
        else:
            value_start, value_end = match.span()
            value_text = match.group(0)
            label_match = _clean_label_span(text[cursor:value_start], cursor)
        if label_match is not None:
            label_text, label_start, label_end = label_match
            label_box = _subbox(block.box, text, label_start, label_end)
            parts.append(
                GenericBlock(
                    block_id=_stable_id(block.source_id, "token_part_label", label_box, label_text, f"{block.block_id}:{index}"),
                    source_id=block.source_id, block_type="part", role="label",
                    text=label_text, normalized_text=normalize_text(label_text),
                    confidence=block.confidence, box=label_box, line_index=block.line_index,
                    sequence_index=block.sequence_index * 100 + index * 2 - 1,
                    parent_block_id=block.block_id, context_text=block.context_text,
                )
            )
        value_box = _subbox(block.box, text, value_start, value_end)
        parts.append(
            GenericBlock(
                block_id=_stable_id(block.source_id, "token_part_value", value_box, value_text, f"{block.block_id}:{index}"),
                source_id=block.source_id, block_type="part", role="value",
                text=value_text.strip(), normalized_text=normalize_text(value_text),
                confidence=block.confidence, box=value_box, line_index=block.line_index,
                sequence_index=block.sequence_index * 100 + index * 2,
                parent_block_id=block.block_id, context_text=block.context_text,
            )
        )
        cursor = value_end

    # Do not manufacture a duplicate for an already atomic value token.
    if len(parts) == 1 and parts[0].role == block.role and parts[0].text.strip() == block.text.strip():
        return [block]
    return parts


def _header_context(lines: Sequence[DetectedLine], current: DetectedLine, width: int) -> str:
    candidates: list[tuple[float, str]] = []
    for line in lines:
        if line.index >= current.index or line.box.y2 > current.box.y1:
            continue
        if current.box.y1 - line.box.y2 > max(160, int(width * 0.14)):
            continue
        if any(looks_like_value(token.text) for token in line.tokens):
            continue
        if not looks_like_label(line.text):
            continue
        horizontal_overlap = max(0, min(line.box.x2, current.box.x2) - max(line.box.x1, current.box.x1))
        overlap_ratio = horizontal_overlap / max(1, min(line.box.width, current.box.width))
        center_distance = abs(_center_x(line.box) - _center_x(current.box)) / max(width, 1)
        vertical_distance = current.box.y1 - line.box.y2
        score = overlap_ratio * 2.0 - center_distance - vertical_distance / max(width, 1)
        candidates.append((score, line.text))
    if not candidates:
        return ""
    return max(candidates, key=lambda item: item[0])[1]


def detect_generic_structure(
    source_id: str,
    image_shape: tuple[int, ...],
    tokens: Sequence[OCRToken],
) -> tuple[list[GenericBlock], list[GenericRelation], dict[str, Any]]:
    """Convert full-page OCR tokens into neutral blocks and label/value proposals.

    No functional field key is assigned here. The result is deliberately generic:
    it describes what was seen and which spatial relations are plausible. A user
    mapping step assigns semantic meaning later.
    """
    height, width = image_shape[:2]
    lines = group_tokens_into_lines(tokens)
    blocks: list[GenericBlock] = []
    relations: list[GenericRelation] = []
    semantic_by_line: dict[int, list[GenericBlock]] = {}

    for line in lines:
        context = _header_context(lines, line, width)
        line_id = _stable_id(source_id, "line", line.box, line.text, str(line.index))
        blocks.append(
            GenericBlock(
                block_id=line_id,
                source_id=source_id,
                block_type="line",
                role="line",
                text=line.text,
                normalized_text=normalize_text(line.text),
                confidence=line.confidence,
                box=line.box,
                line_index=line.index,
                sequence_index=0,
                context_text=context,
            )
        )

        token_blocks: list[GenericBlock] = []
        parts: list[GenericBlock] = []
        for sequence, token in enumerate(line.tokens, start=1):
            assert token.box is not None
            if looks_like_unit(token.text):
                role = "unit"
            elif looks_like_value(token.text):
                role = "value"
            elif looks_like_label(token.text):
                role = "label"
            else:
                role = "unknown"
            token_id = _stable_id(source_id, "token", token.box, token.text, f"{line.index}:{sequence}")
            token_block = GenericBlock(
                block_id=token_id, source_id=source_id, block_type="token", role=role,
                text=token.text, normalized_text=normalize_text(token.text),
                confidence=float(token.confidence), box=token.box, line_index=line.index,
                sequence_index=sequence, parent_block_id=line_id, context_text=context,
            )
            blocks.append(token_block)
            token_blocks.append(token_block)
            token_parts = _split_token_parts(token_block)
            parts.extend(token_parts)
            blocks.extend(item for item in token_parts if item.block_id != token_block.block_id)

        parts.sort(key=lambda item: (item.box.x1, item.sequence_index))
        value_positions = [index for index, block in enumerate(parts) if block.role == "value"]
        semantic: list[GenericBlock] = []

        label_groups = _contiguous_label_groups(parts)
        semantic_labels_line: list[GenericBlock] = []
        for group_index, label_group in enumerate(label_groups, start=1):
            # Lines without a value are contextual headers. Lines with values use
            # the same geometry as actual mapping labels.
            role = "label" if value_positions else "header"
            label = _semantic_label_from_group(
                source_id, line_id, line.index, context, label_group,
                f"{line.index}:{group_index}", role=role,
            )
            blocks.append(label)
            semantic.append(label)
            semantic_labels_line.append(label)

        relation_rank_by_label: dict[str, int] = {}
        if value_positions:
            for value_position in value_positions:
                value_part = parts[value_position]
                value_parts = [value_part]
                unit_block_id: str | None = None
                if value_position + 1 < len(parts):
                    candidate_unit = parts[value_position + 1]
                    horizontal_gap = candidate_unit.box.x1 - value_part.box.x2
                    if candidate_unit.role == "unit" and horizontal_gap <= max(18, value_part.box.height * 1.5):
                        value_parts.append(candidate_unit)
                        unit_block_id = candidate_unit.block_id
                value_box = _union(part.box for part in value_parts)
                value_text = " ".join(part.text for part in value_parts).strip()

                # Preserve the original OCR token as geometry source. Synthetic
                # token parts use parent_block_id to point back to that exact box.
                if value_part.block_type == "part" and value_part.parent_block_id:
                    geometry_parent = value_part.parent_block_id
                else:
                    geometry_parent = value_part.block_id
                row_value = GenericBlock(
                    block_id=_stable_id(source_id, "row_value", value_box, value_text, f"{line.index}:{value_position}"),
                    source_id=source_id, block_type="semantic", role="value",
                    text=value_text, normalized_text=normalize_text(value_text),
                    confidence=sum(part.confidence for part in value_parts) / len(value_parts),
                    box=value_box, line_index=line.index, sequence_index=value_position + 1,
                    parent_block_id=geometry_parent, context_text=context,
                )
                blocks.append(row_value)
                semantic.append(row_value)

                # Choose the nearest *individual* label to the left. Never carry
                # a previous label across unrelated values or panels.
                label_candidates: list[tuple[float, GenericBlock]] = []
                for label in semantic_labels_line:
                    if label.role != "label":
                        continue
                    if label.box.x1 >= row_value.box.x2:
                        continue
                    vertical_delta = abs(_center_y(row_value.box) - _center_y(label.box))
                    if vertical_delta > max(5, 0.60 * max(row_value.box.height, label.box.height)):
                        continue
                    horizontal_gap = max(0, row_value.box.x1 - label.box.x2)
                    # A relation spanning almost a quarter of the image is very
                    # unlikely to be a normal key/value pair. Keep such values
                    # unlabelled instead of fabricating a cross-panel mapping.
                    if horizontal_gap > max(90, width * 0.22):
                        continue
                    alignment = max(
                        0.0,
                        1.0 - vertical_delta / max(row_value.box.height, label.box.height, 1),
                    )
                    distance_factor = math.exp(-horizontal_gap / max(width * 0.12, 1))
                    score = (
                        0.48 * label.confidence
                        + 0.34 * row_value.confidence
                        + 0.12 * alignment
                        + 0.06 * distance_factor
                    )
                    # Prefer the closest label when OCR produced multiple text
                    # regions at exactly the same y-coordinate.
                    score -= horizontal_gap / max(width * 3.0, 1)
                    label_candidates.append((score, label))

                if label_candidates:
                    confidence, selected_label = max(label_candidates, key=lambda item: item[0])
                    relation_rank_by_label[selected_label.block_id] = relation_rank_by_label.get(selected_label.block_id, 0) + 1
                    relation_rank = relation_rank_by_label[selected_label.block_id]
                    label_id: str | None = selected_label.block_id
                    relation_type = "same_line_right"
                else:
                    confidence = row_value.confidence * 0.55
                    relation_rank = 1
                    label_id = None
                    relation_type = "unlabelled_value"

                relation_id = _stable_id(
                    source_id, "relation", row_value.box,
                    f"{label_id or ''}->{row_value.block_id}", str(relation_rank),
                )
                relations.append(
                    GenericRelation(
                        relation_id=relation_id, source_id=source_id,
                        label_block_id=label_id,
                        value_block_id=row_value.block_id, unit_block_id=unit_block_id,
                        relation_type=relation_type,
                        confidence=min(1.0, confidence), rank=relation_rank, context_text=context,
                    )
                )
        semantic_by_line[line.index] = semantic

    # Add a conservative nearest-left relation for value-only lines/cells where
    # the OCR engine split a table row into separate lines. This is generic and
    # remains a proposal requiring mapping confirmation.
    semantic_labels = [block for block in blocks if block.block_type == "semantic" and block.role in {"label", "header"}]
    semantic_values = [block for block in blocks if block.block_type == "semantic" and block.role == "value"]
    related_values = {relation.value_block_id for relation in relations if relation.label_block_id}
    for value in semantic_values:
        if value.block_id in related_values:
            continue
        candidates: list[tuple[float, GenericBlock]] = []
        for label in semantic_labels:
            if label.box.x2 > value.box.x1 + max(8, value.box.width * 0.15):
                continue
            vertical_delta = abs(_center_y(label.box) - _center_y(value.box))
            vertical_limit = max(8.0, 0.70 * max(label.box.height, value.box.height))
            if vertical_delta > vertical_limit:
                continue
            horizontal_gap = value.box.x1 - label.box.x2
            if horizontal_gap < 0 or horizontal_gap > max(90, width * 0.18):
                continue
            score = (
                0.55 * min(label.confidence, value.confidence)
                + 0.30 * max(0.0, 1.0 - vertical_delta / vertical_limit)
                + 0.15 * math.exp(-horizontal_gap / max(width * 0.12, 1))
            )
            candidates.append((score, label))
        if not candidates:
            continue
        score, label = max(candidates, key=lambda item: item[0])
        relation_id = _stable_id(source_id, "relation_nearest", value.box, f"{label.block_id}->{value.block_id}")
        relations.append(
            GenericRelation(
                relation_id=relation_id,
                source_id=source_id,
                label_block_id=label.block_id,
                value_block_id=value.block_id,
                unit_block_id=None,
                relation_type="nearest_left",
                confidence=min(1.0, score),
                rank=1,
                context_text=value.context_text or label.context_text,
            )
        )

    blocks.sort(key=lambda block: (block.box.y1, block.box.x1, block.block_type, block.role))
    relations.sort(key=lambda relation: (-relation.confidence, relation.rank, relation.relation_id))
    diagnostics = {
        "detector_version": GENERIC_DETECTOR_VERSION,
        "image_width": width,
        "image_height": height,
        "ocr_token_count": len([token for token in tokens if token.box is not None and token.text.strip()]),
        "line_count": len(lines),
        "block_count": len(blocks),
        "semantic_label_count": sum(block.role == "label" and block.block_type == "semantic" for block in blocks),
        "semantic_value_count": sum(block.role == "value" and block.block_type == "semantic" for block in blocks),
        "header_count": sum(block.role == "header" and block.block_type == "semantic" for block in blocks),
        "relation_count": len(relations),
    }
    return blocks, relations, diagnostics


def integrate_table_regions(
    source_id: str,
    blocks: Sequence[GenericBlock],
    relations: Sequence[GenericRelation],
    table_regions: Sequence[Any],
) -> tuple[list[GenericBlock], list[GenericRelation], dict[str, Any]]:
    """Add PP-StructureV3 table cells as first-class neutral mapping candidates.

    Full-page OCR remains available for non-table content. Inside confidently
    detected tables, however, row/cell geometry is a stronger signal than
    nearest-neighbour heuristics, so overlapping generic relations are replaced
    by explicit table-cell relations.
    """
    result_blocks = list(blocks)
    table_blocks: list[GenericBlock] = []
    table_relations: list[GenericRelation] = []
    table_value_boxes: list[Box] = []
    accepted_tables = 0
    accepted_cells = 0

    for table_number, table in enumerate(table_regions, start=1):
        cells = list(getattr(table, "cells", ()) or ())
        rows: dict[int, list[Any]] = {}
        for cell in cells:
            rows.setdefault(int(cell.row_index), []).append(cell)
        if len(rows) < 2 or not any(len(items) >= 2 for items in rows.values()):
            continue

        table_box = table.box
        table_block_id = _stable_id(source_id, "table", table_box, "", str(getattr(table, "table_id", table_number)))
        table_context_parts: list[str] = []
        for row_index in sorted(rows):
            row_text = " ".join(str(cell.text or "").strip() for cell in sorted(rows[row_index], key=lambda item: item.column_index) if str(cell.text or "").strip())
            if row_text and row_index <= 2 and not any(looks_like_value(cell.text) for cell in rows[row_index]):
                table_context_parts.append(row_text)
        table_context = " | ".join(table_context_parts[:3])
        table_blocks.append(
            GenericBlock(
                block_id=table_block_id,
                source_id=source_id,
                block_type="table",
                role="table",
                text=table_context,
                normalized_text=normalize_text(table_context),
                confidence=float(getattr(table, "confidence", 0.0) or 0.0),
                box=table_box,
                line_index=-1,
                sequence_index=table_number,
                context_text=table_context,
                table_id=str(getattr(table, "table_id", table_block_id)),
                geometry_source="ppstructurev3_table",
            )
        )

        cell_block_by_id: dict[str, GenericBlock] = {}
        for cell in cells:
            text = str(cell.text or "").strip()
            if looks_like_value(text):
                role = "value"
            elif looks_like_unit(text):
                role = "unit"
            elif looks_like_label(text):
                role = "label"
            else:
                role = "unknown"
            block = GenericBlock(
                block_id=_stable_id(source_id, "table_cell", cell.box, text, str(cell.cell_id)),
                source_id=source_id,
                block_type="table_cell",
                role=role,
                text=text,
                normalized_text=normalize_text(text),
                confidence=float(cell.confidence or getattr(table, "confidence", 0.0) or 0.0),
                box=cell.box,
                line_index=int(cell.row_index),
                sequence_index=int(cell.column_index),
                parent_block_id=table_block_id,
                context_text=table_context,
                table_id=str(getattr(table, "table_id", table_block_id)),
                row_index=int(cell.row_index),
                column_index=int(cell.column_index),
                row_span=int(getattr(cell, "row_span", 1) or 1),
                column_span=int(getattr(cell, "column_span", 1) or 1),
                geometry_source="ppstructurev3_cell",
            )
            cell_block_by_id[str(cell.cell_id)] = block
            table_blocks.append(block)
            accepted_cells += 1

        relation_count_before = len(table_relations)
        for row_index in sorted(rows):
            row_cells = sorted(rows[row_index], key=lambda item: (item.column_index, item.box.x1))
            row_blocks = [cell_block_by_id[str(cell.cell_id)] for cell in row_cells]
            values = [block for block in row_blocks if block.role == "value"]
            if not values:
                continue
            label_candidates = [
                block for block in row_blocks
                if block.role in {"label", "unknown"}
                and block.text
                and any(ch.isalpha() for ch in block.text)
                and block.column_index < min(value.column_index for value in values)
            ]
            if not label_candidates:
                continue
            # Prefer the closest textual cell to the first value; this lets a
            # title/header cell coexist at the left edge without becoming the row label.
            # label_candidates is already filtered to columns left of every value,
            # so the highest column_index is the one closest to the first value.
            label = max(label_candidates, key=lambda block: block.column_index)
            ranked_values = sorted((value for value in values if value.column_index > label.column_index), key=lambda block: block.column_index)
            for rank, value in enumerate(ranked_values, start=1):
                confidence = min(
                    1.0,
                    0.48 * float(getattr(table, "confidence", 0.0) or 0.0)
                    + 0.26 * float(label.confidence)
                    + 0.26 * float(value.confidence),
                )
                relation_id = _stable_id(
                    source_id,
                    "table_relation",
                    value.box,
                    f"{label.block_id}->{value.block_id}",
                    f"{getattr(table, 'table_id', '')}:{row_index}:{rank}",
                )
                table_relations.append(
                    GenericRelation(
                        relation_id=relation_id,
                        source_id=source_id,
                        label_block_id=label.block_id,
                        value_block_id=value.block_id,
                        unit_block_id=None,
                        relation_type="table_cell",
                        confidence=confidence,
                        rank=rank,
                        context_text=table_context,
                        table_id=str(getattr(table, "table_id", table_block_id)),
                        row_index=int(row_index),
                        value_column_index=int(value.column_index),
                    )
                )
                table_value_boxes.append(value.box)
        if len(table_relations) > relation_count_before:
            accepted_tables += 1

    def overlap_ratio(left: Box, right: Box) -> float:
        x = max(0, min(left.x2, right.x2) - max(left.x1, right.x1))
        y = max(0, min(left.y2, right.y2) - max(left.y1, right.y1))
        intersection = x * y
        return intersection / max(1, min(left.width * left.height, right.width * right.height))

    block_by_id = {block.block_id: block for block in blocks}
    kept_relations: list[GenericRelation] = []
    for relation in relations:
        value = block_by_id.get(relation.value_block_id)
        if value is not None and any(overlap_ratio(value.box, table_box) >= 0.55 for table_box in table_value_boxes):
            continue
        kept_relations.append(relation)

    result_blocks.extend(table_blocks)
    result_blocks.sort(key=lambda block: (block.box.y1, block.box.x1, block.block_type, block.role))
    merged_relations = [*table_relations, *kept_relations]
    merged_relations.sort(key=lambda relation: (0 if relation.relation_type == "table_cell" else 1, -relation.confidence, relation.rank, relation.relation_id))
    diagnostics = {
        "table_count": accepted_tables,
        "table_cell_count": accepted_cells,
        "table_relation_count": len(table_relations),
        "generic_relations_replaced": len(relations) - len(kept_relations),
    }
    return result_blocks, merged_relations, diagnostics
