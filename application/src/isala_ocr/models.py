from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Box:
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    def clamp(self, width: int, height: int) -> "Box":
        x1 = min(max(self.x1, 0), width)
        y1 = min(max(self.y1, 0), height)
        x2 = min(max(self.x2, x1), width)
        y2 = min(max(self.y2, y1), height)
        return Box(x1, y1, x2, y2)

    def padded(self, pixels: int) -> "Box":
        return Box(self.x1 - pixels, self.y1 - pixels, self.x2 + pixels, self.y2 + pixels)

    def to_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass
class OCRToken:
    text: str
    confidence: float
    box: Box | None = None


@dataclass
class OCRCandidate:
    variant: str
    text: str
    confidence: float
    value: float | None
    unit: str | None
    valid: bool
    reason: str | None
    score: float
    corrections: list[str] = field(default_factory=list)


@dataclass
class FieldResult:
    key: str
    label: str
    raw_text: str
    value: float | None
    unit: str | None
    confidence: float
    valid: bool
    reason: str | None
    roi: Box
    variant: str
    candidates: list[OCRCandidate] = field(default_factory=list)


@dataclass
class AnchorResult:
    name: str
    expected: str
    observed: str
    similarity: float
    passed: bool
    roi: Box


@dataclass
class ConsistencyResult:
    name: str
    kind: str
    passed: bool | None
    observed: float | None
    expected: float | None
    absolute_delta: float | None
    tolerance: float | None
    fields: list[str]
    reason: str | None = None


@dataclass
class DocumentResult:
    schema_version: str
    source_id: str
    source_file: str
    status: str
    engine: dict[str, Any]
    image: dict[str, Any]
    safe_dicom_metadata: dict[str, Any]
    profile: str
    anchors: list[AnchorResult]
    fields: list[FieldResult]
    consistency: list[ConsistencyResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    study_info: Any | None = None

    def as_dict(self, include_candidates: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        if not include_candidates:
            for field_item in payload["fields"]:
                field_item.pop("candidates", None)
        return payload
