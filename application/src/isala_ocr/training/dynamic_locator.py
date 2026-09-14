from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import median
from typing import Sequence
import re
import unicodedata

from ..config import FieldSpec, Profile
from ..geometry import scale_box
from ..geometry import union as _union
from ..models import Box, OCRToken

LOCATOR_VERSION = "label-row-v2-normalized"


@dataclass(frozen=True)
class DetectedLine:
    tokens: tuple[OCRToken, ...]
    box: Box

    @property
    def text(self) -> str:
        return " ".join(token.text for token in self.tokens if token.text)

    @property
    def center_y(self) -> float:
        return (self.box.y1 + self.box.y2) / 2.0


@dataclass(frozen=True)
class LocatedField:
    field: FieldSpec
    box: Box
    method: str
    locator_confidence: float
    matched_label: str
    matched_label_box: Box | None
    panel: str | None
    value_tokens: tuple[OCRToken, ...] = ()


def _center_x(box: Box) -> float:
    return (box.x1 + box.x2) / 2.0


def _center_y(box: Box) -> float:
    return (box.y1 + box.y2) / 2.0


def normalize_for_matching(value: str) -> str:
    """Normalize only locator labels, never the OCR training transcript."""
    normalized = unicodedata.normalize("NFKD", value).casefold()
    normalized = normalized.replace("²", "2")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _similarity(expected: str, observed: str) -> float:
    left = normalize_for_matching(expected)
    right = normalize_for_matching(observed)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    ratio = SequenceMatcher(None, left, right).ratio()
    # ED/ES and BSA are semantic discriminators, not harmless OCR noise.
    # A fuzzy match must not map ED Volume to ES Volume or a BSA row to the
    # non-indexed field merely because most characters overlap.
    compact_left = left.replace(" ", "")
    compact_right = right.replace(" ", "")
    for prefix in ("ed", "es"):
        if compact_left.startswith(prefix) and not compact_right.startswith(prefix):
            ratio *= 0.35
    if ("bsa" in compact_left) != ("bsa" in compact_right):
        ratio *= 0.45
    # Prevent short labels such as "ED Volume" from winning over
    # "ED Volume/BSA" when an exact row is also available.
    length_penalty = min(abs(len(left) - len(right)) / max(len(left), 1), 0.35)
    return max(0.0, ratio - 0.35 * length_penalty)


def group_tokens_into_lines(tokens: Sequence[OCRToken]) -> list[DetectedLine]:
    usable = [token for token in tokens if token.text.strip() and token.box is not None]
    usable.sort(key=lambda token: (_center_y(token.box), token.box.x1))
    if not usable:
        return []

    heights = [max(token.box.height, 1) for token in usable]
    typical_height = max(8.0, float(median(heights)))
    lines: list[list[OCRToken]] = []

    for token in usable:
        token_center = _center_y(token.box)
        best_index: int | None = None
        best_distance = float("inf")
        for index, line_tokens in enumerate(lines):
            line_center = median(_center_y(item.box) for item in line_tokens)
            # Adjacent table rows are only ~24 px apart in the Philips UI.
            # OCR engines may return unusually tall word boxes, so never let
            # box height inflate the line-merging tolerance beyond 12 px.
            tolerance = max(5.0, min(12.0, typical_height * 0.45))
            distance = abs(token_center - line_center)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            lines.append([token])
        else:
            lines[best_index].append(token)

    result: list[DetectedLine] = []
    for line_tokens in lines:
        line_tokens.sort(key=lambda item: item.box.x1)
        result.append(
            DetectedLine(tokens=tuple(line_tokens), box=_union(item.box for item in line_tokens))
        )
    result.sort(key=lambda line: (line.center_y, line.box.x1))
    return result


def _best_span(
    tokens: Sequence[OCRToken], aliases: Sequence[str], max_words: int = 5
) -> tuple[float, str, Box | None, tuple[OCRToken, ...]]:
    best = (0.0, "", None, ())
    ordered = [token for token in tokens if token.box is not None and token.text.strip()]
    for start in range(len(ordered)):
        for length in range(1, min(max_words, len(ordered) - start) + 1):
            span = tuple(ordered[start : start + length])
            text = " ".join(token.text for token in span)
            score = max((_similarity(alias, text) for alias in aliases), default=0.0)
            if score > best[0]:
                best = (score, text, _union(token.box for token in span), span)
    return best


def _scaled_x(value: float, profile: Profile, width: int) -> int:
    return int(round(float(value) * width / profile.reference_width))


def _scaled_y(value: float, profile: Profile, height: int) -> int:
    return int(round(float(value) * height / profile.reference_height))


def _panel_divider(
    lines: Sequence[DetectedLine], profile: Profile, width: int, height: int
) -> tuple[int, float, str]:
    settings = profile.dynamic_extraction
    aliases = tuple(
        str(value)
        for value in settings.get(
            "right_panel_titles", ["Right ventricle Volume Result"]
        )
    )
    panel_x2 = _scaled_x(settings.get("panel_search_x2", 650), profile, width)
    candidates: list[tuple[float, int, str]] = []
    for line in lines:
        if line.center_y < height * 0.25:
            continue
        panel_tokens = [token for token in line.tokens if _center_x(token.box) <= panel_x2]
        score, text, box, _ = _best_span(panel_tokens, aliases, max_words=6)
        if box is not None:
            candidates.append((score, box.y1, text))
    threshold = float(settings.get("panel_title_threshold", 0.68))
    passing = [item for item in candidates if item[0] >= threshold]
    if passing:
        score, divider, text = min(passing, key=lambda item: item[1])
        return max(1, divider), score, text
    return int(round(height * float(settings.get("fallback_panel_divider", 0.55)))), 0.0, ""


def _panel_bounds(panel: str | None, divider: int, height: int) -> tuple[int, int]:
    if panel == "lv":
        return 0, divider
    if panel == "rv":
        return divider, height
    return 0, height


def _value_column(
    lines: Sequence[DetectedLine],
    profile: Profile,
    panel: str | None,
    divider: int,
    width: int,
    height: int,
) -> tuple[int, int, float]:
    settings = profile.dynamic_extraction
    panel_y1, panel_y2 = _panel_bounds(panel, divider, height)
    endo_aliases = tuple(str(value) for value in settings.get("value_headers", ["Endo Volume"]))
    normal_aliases = tuple(
        str(value) for value in settings.get("normal_headers", ["Normal Values"])
    )
    search_x1 = _scaled_x(settings.get("header_search_x1", 130), profile, width)
    search_x2 = _scaled_x(settings.get("header_search_x2", 650), profile, width)

    best_endo = (0.0, "", None, ())
    best_normal = (0.0, "", None, ())
    for line in lines:
        if not (panel_y1 <= line.center_y < panel_y2):
            continue
        tokens = [
            token
            for token in line.tokens
            if search_x1 <= _center_x(token.box) <= search_x2
        ]
        endo = _best_span(tokens, endo_aliases, max_words=4)
        normal = _best_span(tokens, normal_aliases, max_words=4)
        if endo[0] > best_endo[0]:
            best_endo = endo
        if normal[0] > best_normal[0]:
            best_normal = normal

    fallback = settings.get("fallback_value_column", [175, 390])
    fallback_x1 = _scaled_x(fallback[0], profile, width)
    fallback_x2 = _scaled_x(fallback[1], profile, width)
    header_threshold = float(settings.get("header_match_threshold", 0.62))
    confidence = 0.0

    if best_endo[2] is not None and best_endo[0] >= header_threshold:
        header_box: Box = best_endo[2]
        x1 = max(0, header_box.x1 - _scaled_x(settings.get("header_left_padding", 35), profile, width))
        confidence = best_endo[0]
    else:
        x1 = fallback_x1

    if best_normal[2] is not None and best_normal[0] >= header_threshold:
        normal_box: Box = best_normal[2]
        x2 = normal_box.x1 - _scaled_x(settings.get("normal_column_gap", 15), profile, width)
        confidence = max(confidence, best_normal[0])
    else:
        x2 = fallback_x2

    if x2 <= x1 + 20:
        x1, x2 = fallback_x1, fallback_x2
        confidence = 0.0
    return max(0, x1), min(width, x2), confidence


def _field_aliases(
    field: FieldSpec,
    learned_aliases: dict[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    configured = tuple(field.screen_labels)
    learned = tuple((learned_aliases or {}).get(field.key, ()))
    if configured or learned:
        # Keep profile aliases first for deterministic ties, then append unique
        # reviewed OCR variants learned in the row-header normalization step.
        values: list[str] = []
        seen: set[str] = set()
        for value in (*configured, *learned):
            normalized = normalize_for_matching(str(value))
            if normalized and normalized not in seen:
                seen.add(normalized)
                values.append(str(value))
        return tuple(values)
    # Last-resort compatibility for old profiles. The Philips table label is
    # generally the descriptive label without the ventricle prefix.
    label = field.label
    for prefix in ("Left ventricle ", "Right ventricle "):
        if label.startswith(prefix):
            label = label[len(prefix) :]
    return (label,)


def _locate_label(
    lines: Sequence[DetectedLine],
    field: FieldSpec,
    profile: Profile,
    divider: int,
    width: int,
    height: int,
    learned_aliases: dict[str, Sequence[str]] | None = None,
) -> tuple[float, str, Box | None, tuple[OCRToken, ...]]:
    settings = profile.dynamic_extraction
    label_column = settings.get("fallback_label_column", [0, 175])
    label_x1 = _scaled_x(label_column[0], profile, width)
    label_x2 = _scaled_x(label_column[1], profile, width)
    panel_y1, panel_y2 = _panel_bounds(field.panel, divider, height)
    aliases = _field_aliases(field, learned_aliases)
    best = (0.0, "", None, ())
    for line in lines:
        if not (panel_y1 <= line.center_y < panel_y2):
            continue
        tokens = [
            token
            for token in line.tokens
            if label_x1 <= _center_x(token.box) <= label_x2
        ]
        candidate = _best_span(tokens, aliases, max_words=4)
        if candidate[0] > best[0]:
            best = candidate
    return best


def locate_fields(
    image_shape: tuple[int, ...],
    tokens: Sequence[OCRToken],
    profile: Profile,
    padding_pixels: int = 2,
    learned_aliases: dict[str, Sequence[str]] | None = None,
) -> tuple[list[LocatedField], dict[str, object]]:
    """Locate value rows from screen labels and table geometry.

    The locator uses normalized text only to find table labels. The crop pixels
    and later recognition transcript remain untouched.
    """
    height, width = image_shape[:2]
    lines = group_tokens_into_lines(tokens)
    divider, divider_confidence, divider_text = _panel_divider(
        lines, profile, width, height
    )
    settings = profile.dynamic_extraction
    label_threshold = float(settings.get("label_match_threshold", 0.72))
    row_half_height = max(
        8,
        _scaled_y(settings.get("row_half_height", 13), profile, height),
    )
    value_padding = max(
        1,
        _scaled_x(settings.get("value_padding", 5), profile, width),
    )
    fallback_enabled = bool(settings.get("fallback_to_fixed_roi", True))

    columns: dict[str | None, tuple[int, int, float]] = {}
    for panel in {field.panel for field in profile.fields}:
        columns[panel] = _value_column(
            lines, profile, panel, divider, width, height
        )

    located: list[LocatedField] = []
    for field in profile.fields:
        score, matched_text, label_box, label_tokens = _locate_label(
            lines, field, profile, divider, width, height, learned_aliases
        )
        if label_box is not None and score >= label_threshold:
            x1, x2, header_confidence = columns[field.panel]
            row_center = float(median(_center_y(token.box) for token in label_tokens))
            y1 = max(0, int(round(row_center - row_half_height)))
            y2 = min(height, int(round(row_center + row_half_height)))
            value_tokens = tuple(
                token
                for token in tokens
                if token.box is not None
                and x1 <= _center_x(token.box) <= x2
                and y1 <= _center_y(token.box) <= y2
                and token.text.strip()
            )
            if value_tokens:
                token_box = _union(token.box for token in value_tokens)
                vertical_padding = max(2, _scaled_y(3, profile, height))
                token_y1 = max(y1, token_box.y1 - vertical_padding)
                token_y2 = min(y2, token_box.y2 + vertical_padding)
                if token_y2 - token_y1 < 8:
                    token_y1, token_y2 = y1, y2
                box = Box(
                    max(x1, token_box.x1 - value_padding),
                    token_y1,
                    min(x2, token_box.x2 + value_padding),
                    token_y2,
                ).padded(padding_pixels).clamp(width, height)
                method = "dynamic_token_box"
                token_confidence = sum(token.confidence for token in value_tokens) / len(value_tokens)
                confidence = 0.65 * score + 0.20 * header_confidence + 0.15 * token_confidence
            else:
                box = Box(x1, y1, x2, y2).padded(padding_pixels).clamp(width, height)
                method = "dynamic_row_band"
                confidence = 0.75 * score + 0.25 * header_confidence
            located.append(
                LocatedField(
                    field=field,
                    box=box,
                    method=method,
                    locator_confidence=round(min(max(confidence, 0.0), 1.0), 4),
                    matched_label=matched_text,
                    matched_label_box=label_box,
                    panel=field.panel,
                    value_tokens=value_tokens,
                )
            )
            continue

        if fallback_enabled:
            fallback = scale_box(
                field.roi,
                profile.reference_width,
                profile.reference_height,
                width,
                height,
            ).padded(padding_pixels).clamp(width, height)
            located.append(
                LocatedField(
                    field=field,
                    box=fallback,
                    method="fixed_fallback",
                    locator_confidence=round(score, 4),
                    matched_label=matched_text,
                    matched_label_box=label_box,
                    panel=field.panel,
                )
            )

    diagnostics = {
        "locator_version": LOCATOR_VERSION,
        "learned_alias_fields": len(learned_aliases or {}),
        "learned_alias_count": sum(len(values) for values in (learned_aliases or {}).values()),
        "detected_tokens": len([token for token in tokens if token.box is not None]),
        "detected_lines": len(lines),
        "panel_divider_y": divider,
        "panel_divider_confidence": round(divider_confidence, 4),
        "panel_divider_text": divider_text,
        "columns": {
            str(panel): {"x1": values[0], "x2": values[1], "confidence": round(values[2], 4)}
            for panel, values in columns.items()
        },
    }
    return located, diagnostics
