from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FieldSpec
from .models import OCRCandidate


NUMBER_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
DASH_PATTERN = re.compile(r"^\s*[-–—]\s*$")


@dataclass(frozen=True)
class ParsedValue:
    value: float | None
    unit: str | None
    normalized_text: str
    corrections: list[str]


def _normalize_numeric_context(text: str) -> tuple[str, list[str]]:
    cleaned = text.strip().replace("\u00a0", " ")
    cleaned = cleaned.replace("−", "-").replace("–", "-").replace("—", "-")
    corrections: list[str] = []

    replacements = {
        "O": "0",
        "o": "0",
        "I": "1",
        "l": "1",
        "|": "1",
    }
    chars = list(cleaned)
    for index, char in enumerate(chars):
        if char not in replacements:
            continue
        left_numeric = index > 0 and (chars[index - 1].isdigit() or chars[index - 1] in ".,")
        right_numeric = index + 1 < len(chars) and (chars[index + 1].isdigit() or chars[index + 1] in ".,")
        if left_numeric or right_numeric:
            chars[index] = replacements[char]
            corrections.append(f"{char}->{chars[index]}")
    cleaned = "".join(chars)
    cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", cleaned)
    return cleaned, corrections


def parse_value(text: str, expected_unit: str | None) -> ParsedValue:
    normalized, corrections = _normalize_numeric_context(text)
    if DASH_PATTERN.match(normalized):
        return ParsedValue(None, expected_unit, normalized, corrections)

    match = NUMBER_PATTERN.search(normalized)
    if not match:
        return ParsedValue(None, None, normalized, corrections)
    numeric = match.group(0).replace(",", ".")
    value = float(numeric)
    remainder = (normalized[: match.start()] + " " + normalized[match.end() :]).strip()
    unit = remainder or expected_unit
    return ParsedValue(value, unit, normalized, corrections)


def _unit_similarity(observed: str | None, expected: str | None) -> float:
    if not expected:
        return 1.0
    if not observed:
        return 0.35
    normalize = lambda value: re.sub(r"[^a-z0-9%]", "", value.lower().replace("²", "2"))
    left = normalize(observed)
    right = normalize(expected)
    if left == right:
        return 1.0
    if right in left or left in right:
        return 0.8
    # OCR commonly reads superscript 2 as *, apostrophe or nothing.
    aliases = {
        "mlm2": {"mlm", "mim", "mum", "mlm2", "mim2"},
        "lmin": {"lmin", "imin", "1min"},
    }
    if right in aliases and left in aliases[right]:
        return 0.75
    return 0.0


def evaluate_candidate(
    spec: FieldSpec,
    variant: str,
    text: str,
    confidence: float,
) -> OCRCandidate:
    parsed = parse_value(text, spec.unit)
    reason: str | None = None
    valid = True

    # OCR sometimes drops the decimal separator in compact UI values (e.g. 643 -> 64.3).
    # Only infer it when the unmodified value violates the configured range.
    inferred_decimal = False
    if (
        parsed.value is not None
        and spec.decimals
        and spec.decimals > 0
        and spec.maximum is not None
        and parsed.value > spec.maximum
    ):
        numeric_match = NUMBER_PATTERN.search(parsed.normalized_text)
        if numeric_match and "." not in numeric_match.group(0) and "," not in numeric_match.group(0):
            adjusted = parsed.value / (10 ** spec.decimals)
            minimum_ok = spec.minimum is None or adjusted >= spec.minimum
            maximum_ok = adjusted <= spec.maximum
            if minimum_ok and maximum_ok:
                parsed = ParsedValue(
                    adjusted,
                    parsed.unit,
                    parsed.normalized_text,
                    parsed.corrections + [f"inferred_decimal:{parsed.value}->{adjusted}"],
                )
                inferred_decimal = True

    if parsed.value is None:
        if spec.allow_missing and DASH_PATTERN.match(parsed.normalized_text):
            valid = True
        else:
            valid = False
            reason = "no_numeric_value"
    else:
        if spec.minimum is not None and parsed.value < spec.minimum:
            valid = False
            reason = f"below_minimum:{spec.minimum}"
        if spec.maximum is not None and parsed.value > spec.maximum:
            valid = False
            reason = f"above_maximum:{spec.maximum}"

    unit_score = _unit_similarity(parsed.unit, spec.unit)
    score = max(0.0, min(1.0, confidence))
    score += 1.5 if valid else -0.5
    score += 0.35 * unit_score
    if parsed.value is not None:
        score += 0.25
    if inferred_decimal:
        score -= 0.05
    if spec.unit and unit_score == 0:
        score -= 0.15

    return OCRCandidate(
        variant=variant,
        text=text,
        confidence=float(max(0.0, min(1.0, confidence))),
        value=parsed.value,
        unit=spec.unit if parsed.value is not None or spec.allow_missing else parsed.unit,
        valid=bool(valid),
        reason=reason,
        score=float(round(score, 6)),
        corrections=parsed.corrections,
    )
