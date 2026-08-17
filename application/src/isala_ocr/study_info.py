from __future__ import annotations

from dataclasses import asdict, dataclass, field
from statistics import median
from typing import Sequence
import re

from .models import Box, OCRToken


@dataclass(frozen=True)
class StudyInfoResult:
    """Structured values parsed from the Philips ``Study info`` line.

    The six output values are deliberately exposed as named fields.  ``raw_values``
    preserves the exact OCR fragments so downstream users can distinguish parsing
    from the text that the OCR engine actually returned.
    """

    detected: bool
    raw_text: str
    confidence: float
    roi: Box | None
    heart_rate_bpm: int | None = None
    bsa_m2: float | None = None
    bsa_method: str | None = None
    height_m: float | None = None
    weight_kg: float | None = None
    gender: str | None = None
    raw_values: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, float] = field(default_factory=dict)
    valid: dict[str, bool] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _Line:
    tokens: tuple[OCRToken, ...]
    box: Box

    @property
    def text(self) -> str:
        return " ".join(token.text.strip() for token in self.tokens if token.text.strip()).strip()

    @property
    def confidence(self) -> float:
        weights = [max(len(token.text.strip()), 1) for token in self.tokens if token.text.strip()]
        if not weights:
            return 0.0
        values = [token for token in self.tokens if token.text.strip()]
        return float(
            sum(token.confidence * weight for token, weight in zip(values, weights, strict=True))
            / sum(weights)
        )


def _center_y(box: Box) -> float:
    return (box.y1 + box.y2) / 2.0


def _union(boxes: Sequence[Box]) -> Box:
    return Box(
        min(box.x1 for box in boxes),
        min(box.y1 for box in boxes),
        max(box.x2 for box in boxes),
        max(box.y2 for box in boxes),
    )


def _lines(tokens: Sequence[OCRToken]) -> list[_Line]:
    usable = [token for token in tokens if token.box is not None and token.text.strip()]
    usable.sort(key=lambda token: (_center_y(token.box), token.box.x1))
    if not usable:
        return []

    typical_height = max(6.0, float(median(max(token.box.height, 1) for token in usable)))
    tolerance = max(4.0, min(12.0, typical_height * 0.55))
    groups: list[list[OCRToken]] = []
    for token in usable:
        token_y = _center_y(token.box)
        best_index: int | None = None
        best_distance = float("inf")
        for index, group in enumerate(groups):
            group_y = float(median(_center_y(item.box) for item in group))
            distance = abs(token_y - group_y)
            if distance <= tolerance and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            groups.append([token])
        else:
            groups[best_index].append(token)

    result: list[_Line] = []
    for group in groups:
        group.sort(key=lambda token: token.box.x1)
        result.append(_Line(tuple(group), _union([token.box for token in group])))
    return sorted(result, key=lambda line: (line.box.y1, line.box.x1))


def _number(value: str) -> float:
    return float(value.strip().replace(",", "."))


def _raw(match: re.Match[str]) -> str:
    return " ".join(match.group("raw").strip().split())


_PATTERNS = {
    "heart_rate_bpm": re.compile(
        r"\bH\s*R\b\s*[:=]?\s*(?P<raw>(?P<value>\d{1,3}(?:[.,]\d+)?)\s*(?:b\s*p\s*m)?)",
        re.IGNORECASE,
    ),
    "bsa_m2": re.compile(
        r"\bB\s*S\s*A\b\s*[:=]?\s*(?P<raw>(?P<value>\d(?:[.,]\d{1,3})?)\s*"
        r"(?:m\s*(?:²|2|\^\s*2))?\s*(?:\((?P<method>[^)]+)\))?)",
        re.IGNORECASE,
    ),
    "height": re.compile(
        r"\bHeight\b\s*[:=]?\s*(?P<raw>(?P<value>\d{1,3}(?:[.,]\d{1,3})?)\s*(?P<unit>cm|m)?)",
        re.IGNORECASE,
    ),
    "weight_kg": re.compile(
        r"\bWeight\b\s*[:=]?\s*(?P<raw>(?P<value>\d{1,3}(?:[.,]\d{1,2})?)\s*(?:k\s*g)?)",
        re.IGNORECASE,
    ),
    "gender": re.compile(
        r"\bGender\b\s*[:=]?\s*(?P<raw>(?P<value>[A-Za-z][A-Za-z-]{0,15}))",
        re.IGNORECASE,
    ),
}


def _candidate_score(line: _Line) -> tuple[int, float]:
    text = line.text
    found = sum(1 for pattern in _PATTERNS.values() if pattern.search(text))
    lowered = text.casefold()
    has_heading = bool(re.search(r"\bstudy\s*info\b", lowered))
    if found < 3 and not (has_heading and found >= 2):
        return 0, 0.0
    return found, line.confidence


def extract_study_info(tokens: Sequence[OCRToken]) -> StudyInfoResult:
    """Parse the best Study info line from full-page detector tokens.

    Multiple copies can occur in a Philips result screen.  The line with the
    most independently parsed fields wins; OCR confidence breaks ties.
    """

    candidates = [(line, _candidate_score(line)) for line in _lines(tokens)]
    candidates = [(line, score) for line, score in candidates if score[0] > 0]
    if not candidates:
        return StudyInfoResult(
            detected=False,
            raw_text="",
            confidence=0.0,
            roi=None,
            valid={
                "heart_rate_bpm": False,
                "bsa_m2": False,
                "height_m": False,
                "weight_kg": False,
                "gender": False,
            },
            warnings=["study_info_line_not_found"],
        )

    line, _ = max(candidates, key=lambda item: (item[1][0], item[1][1]))
    text = line.text
    confidence = round(line.confidence, 4)
    raw_values: dict[str, str] = {}
    field_confidence: dict[str, float] = {}
    valid: dict[str, bool] = {}
    warnings: list[str] = []

    heart_rate_bpm: int | None = None
    match = _PATTERNS["heart_rate_bpm"].search(text)
    if match:
        raw_values["heart_rate_bpm"] = _raw(match)
        value = _number(match.group("value"))
        heart_rate_bpm = int(round(value)) if abs(value - round(value)) < 0.001 else int(value)
        valid["heart_rate_bpm"] = 20 <= value <= 300
        field_confidence["heart_rate_bpm"] = confidence
    else:
        valid["heart_rate_bpm"] = False

    bsa_m2: float | None = None
    bsa_method: str | None = None
    match = _PATTERNS["bsa_m2"].search(text)
    if match:
        raw_values["bsa_m2"] = _raw(match)
        bsa_m2 = _number(match.group("value"))
        method = (match.group("method") or "").strip()
        bsa_method = method or None
        if method:
            raw_values["bsa_method"] = method
            field_confidence["bsa_method"] = confidence
        valid["bsa_m2"] = 0.3 <= bsa_m2 <= 5.0
        valid["bsa_method"] = bool(bsa_method)
        field_confidence["bsa_m2"] = confidence
    else:
        valid["bsa_m2"] = False
        valid["bsa_method"] = False

    height_m: float | None = None
    match = _PATTERNS["height"].search(text)
    if match:
        raw_values["height_m"] = _raw(match)
        value = _number(match.group("value"))
        unit = (match.group("unit") or "m").casefold()
        height_m = value / 100.0 if unit == "cm" else value
        valid["height_m"] = 0.3 <= height_m <= 3.0
        field_confidence["height_m"] = confidence
    else:
        valid["height_m"] = False

    weight_kg: float | None = None
    match = _PATTERNS["weight_kg"].search(text)
    if match:
        raw_values["weight_kg"] = _raw(match)
        weight_kg = _number(match.group("value"))
        valid["weight_kg"] = 1.0 <= weight_kg <= 500.0
        field_confidence["weight_kg"] = confidence
    else:
        valid["weight_kg"] = False

    gender: str | None = None
    match = _PATTERNS["gender"].search(text)
    if match:
        raw_values["gender"] = _raw(match)
        gender = match.group("value").strip()
        valid["gender"] = bool(gender)
        field_confidence["gender"] = confidence
    else:
        valid["gender"] = False

    required = ("heart_rate_bpm", "bsa_m2", "height_m", "weight_kg", "gender")
    for key in required:
        if key not in raw_values:
            warnings.append(f"study_info_field_missing:{key}")
        elif not valid.get(key, False):
            warnings.append(f"study_info_field_out_of_range:{key}")

    return StudyInfoResult(
        detected=True,
        raw_text=text,
        confidence=confidence,
        roi=line.box,
        heart_rate_bpm=heart_rate_bpm,
        bsa_m2=bsa_m2,
        bsa_method=bsa_method,
        height_m=height_m,
        weight_kg=weight_kg,
        gender=gender,
        raw_values=raw_values,
        field_confidence=field_confidence,
        valid=valid,
        warnings=warnings,
    )
