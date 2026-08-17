from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import cv2
import numpy as np

from ..models import Box, OCRToken
from ..ocr.table_structure import TableRegion

from .detection_gate import greedy_detection_metrics, intersection_over_union, passes_detection_gate
from .projects import resolve_project_workspace
LOCALIZATION_CANDIDATE_VERSION = "field-localization-fusion-v1"
VALID_DETECTION_REVIEW_STATUSES = {"correct", "adjusted", "rejected", "added"}
VALID_DETECTION_RELEVANCE_STATUSES = {"unreviewed", "relevant", "irrelevant"}
DETECTION_REVIEW_REASONS = {
    "too_small": "Te klein",
    "too_large": "Te groot",
    "misplaced": "Verkeerd geplaatst",
    "false_positive": "Geen veld / false positive",
    "merged_fields": "Meerdere velden/cellen samengevoegd",
    "split_field": "Eén veld opgesplitst",
    "table_geometry_error": "Tabel/cel fout",
    "other": "Andere reden",
}


@dataclass(frozen=True)
class LocalizationCandidate:
    candidate_id: str
    source_id: str
    box: Box
    confidence: float
    source_kind: str
    source_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_id": self.source_id,
            "x1": self.box.x1,
            "y1": self.box.y1,
            "x2": self.box.x2,
            "y2": self.box.y2,
            "confidence": float(self.confidence),
            "source_kind": self.source_kind,
            "source_refs": list(self.source_refs),
        }


def _stable_id(source_id: str, box: Box, source_kind: str, refs: Iterable[str] = ()) -> str:
    payload = f"{source_id}|{box.x1},{box.y1},{box.x2},{box.y2}|{source_kind}|{'|'.join(sorted(refs))}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _coverage(inner: Box, outer: Box) -> float:
    ix1, iy1 = max(inner.x1, outer.x1), max(inner.y1, outer.y1)
    ix2, iy2 = min(inner.x2, outer.x2), min(inner.y2, outer.y2)
    intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    return intersection / max(1, inner.width * inner.height)


def _valid_box(box: Box, width: int, height: int) -> bool:
    if box.width < 4 or box.height < 4:
        return False
    if box.width > width * 0.85 or box.height > height * 0.30:
        return False
    return True


def text_geometry_candidates(
    source_id: str,
    tokens: Sequence[OCRToken],
    *,
    image_width: int,
    image_height: int,
    padding: int = 2,
) -> list[LocalizationCandidate]:
    """Convert OCR geometry to neutral candidates without storing recognized text.

    Text recognition is used only as a way to obtain stable text boxes. The text
    itself is deliberately discarded in Pipeline A.
    """
    result: list[LocalizationCandidate] = []
    for index, token in enumerate(tokens):
        if token.box is None or not str(token.text or "").strip():
            continue
        box = token.box.padded(padding).clamp(image_width, image_height)
        if not _valid_box(box, image_width, image_height):
            continue
        ref = f"ocr:{index}"
        result.append(
            LocalizationCandidate(
                candidate_id=_stable_id(source_id, box, "text_geometry", (ref,)),
                source_id=source_id,
                box=box,
                confidence=max(0.0, min(1.0, float(token.confidence))),
                source_kind="text_geometry",
                source_refs=(ref,),
            )
        )
    return result


def table_cell_candidates(
    source_id: str,
    tables: Sequence[TableRegion],
    *,
    image_width: int,
    image_height: int,
    include_broad_cells: bool = False,
) -> list[LocalizationCandidate]:
    result: list[LocalizationCandidate] = []
    for table in tables:
        for cell in table.cells:
            box = cell.box.clamp(image_width, image_height)
            if not _valid_box(box, image_width, image_height):
                continue
            # Legacy loose-field fusion suppresses very broad table cells because
            # they are poor text-like ROI candidates. In table-first mode the cell
            # itself is the semantic geometry, so broad label/value cells must stay.
            if not include_broad_cells and (
                box.width > image_width * 0.45 or box.height > image_height * 0.12
            ):
                continue
            ref = f"table:{table.table_id}:cell:{cell.cell_id}"
            result.append(
                LocalizationCandidate(
                    candidate_id=_stable_id(source_id, box, "table_cell", (ref,)),
                    source_id=source_id,
                    box=box,
                    confidence=max(0.0, min(1.0, float(cell.confidence or table.confidence))),
                    source_kind="table_cell",
                    source_refs=(ref,),
                )
            )
    return result


def fuse_candidates(
    source_id: str,
    candidates: Sequence[LocalizationCandidate],
    *,
    iou_threshold: float = 0.55,
    containment_threshold: float = 0.92,
) -> list[LocalizationCandidate]:
    """Fuse overlapping geometry using NMS while preserving source provenance."""
    ordered = sorted(
        candidates,
        key=lambda item: (
            1 if item.source_kind == "trained_detector" else 0,
            item.confidence,
            -(item.box.width * item.box.height),
        ),
        reverse=True,
    )
    output: list[LocalizationCandidate] = []
    for candidate in ordered:
        match_index: int | None = None
        for index, existing in enumerate(output):
            iou = intersection_over_union(candidate.box, existing.box)
            contained = max(_coverage(candidate.box, existing.box), _coverage(existing.box, candidate.box))
            if iou >= iou_threshold or contained >= containment_threshold:
                match_index = index
                break
        if match_index is None:
            output.append(candidate)
            continue
        existing = output[match_index]
        # Prefer the tighter box unless the trained detector has materially higher
        # confidence. This avoids replacing a precise OCR token with a whole cell.
        existing_area = existing.box.width * existing.box.height
        candidate_area = candidate.box.width * candidate.box.height
        choose_candidate = (
            candidate.source_kind == "trained_detector" and candidate.confidence >= existing.confidence + 0.08
        ) or (candidate_area < existing_area * 0.82 and candidate.confidence >= existing.confidence - 0.08)
        chosen = candidate if choose_candidate else existing
        refs = tuple(sorted(set(existing.source_refs) | set(candidate.source_refs)))
        kinds = sorted(set(existing.source_kind.split("+") + candidate.source_kind.split("+")))
        output[match_index] = LocalizationCandidate(
            candidate_id=_stable_id(source_id, chosen.box, "+".join(kinds), refs),
            source_id=source_id,
            box=chosen.box,
            confidence=max(existing.confidence, candidate.confidence),
            source_kind="+".join(kinds),
            source_refs=refs,
        )
    return sorted(output, key=lambda item: (item.box.y1, item.box.x1, item.box.y2, item.box.x2))


def write_candidate_crops(
    workspace: str | Path,
    source_id: str,
    image: np.ndarray,
    candidates: Sequence[LocalizationCandidate],
) -> dict[str, str]:
    root = resolve_project_workspace(workspace) / "detection_candidate_crops" / source_id
    root.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    height, width = image.shape[:2]
    for candidate in candidates:
        box = candidate.box.clamp(width, height)
        crop = image[box.y1:box.y2, box.x1:box.x2]
        if not crop.size:
            continue
        path = root / f"{candidate.candidate_id}.png"
        if cv2.imwrite(str(path), crop):
            paths[candidate.candidate_id] = path.relative_to(resolve_project_workspace(workspace)).as_posix()
    return paths


def trained_detector_candidates(
    source_id: str,
    predictions: Sequence[dict[str, Any]],
    *,
    image_width: int,
    image_height: int,
    minimum_confidence: float = 0.25,
    model_id: str = "",
) -> list[LocalizationCandidate]:
    """Convert object-detector prediction JSON into neutral geometry candidates."""
    result: list[LocalizationCandidate] = []
    for index, item in enumerate(predictions):
        try:
            score = float(item.get("score") or item.get("confidence") or 0.0)
            coordinate = item.get("coordinate") or item.get("bbox") or item.get("box")
            if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 4:
                continue
            values = [float(value) for value in coordinate]
            # PaddleX prediction coordinates are xyxy. Accept an explicit xywh
            # marker for test fixtures or alternative exporters.
            if str(item.get("bbox_format") or "xyxy").lower() == "xywh":
                x1, y1, width, height = values
                x2, y2 = x1 + width, y1 + height
            else:
                x1, y1, x2, y2 = values
            box = Box(
                max(0, int(round(x1))), max(0, int(round(y1))),
                min(image_width, int(round(x2))), min(image_height, int(round(y2))),
            )
        except (TypeError, ValueError):
            continue
        if score < minimum_confidence or not _valid_box(box, image_width, image_height):
            continue
        ref = f"model:{model_id or 'active'}:{index}"
        result.append(
            LocalizationCandidate(
                candidate_id=_stable_id(source_id, box, "trained_detector", (ref,)),
                source_id=source_id,
                box=box,
                confidence=max(0.0, min(1.0, score)),
                source_kind="trained_detector",
                source_refs=(ref,),
            )
        )
    return result
