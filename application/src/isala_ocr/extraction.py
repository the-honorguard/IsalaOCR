from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

import cv2
import numpy as np

from .config import Profile
from .geometry import scale_box
from .models import AnchorResult, FieldResult, OCRCandidate
from .ocr.base import OCREngine
from .preprocess import make_variants
from .validation import evaluate_candidate


@dataclass(frozen=True)
class ExtractionSettings:
    variants: tuple[str, ...]
    upscale_factor: float
    padding_pixels: int
    minimum_confidence: float
    verify_anchors: bool


def _join_tokens(tokens) -> tuple[str, float]:
    if not tokens:
        return "", 0.0
    ordered = sorted(
        tokens,
        key=lambda token: (
            token.box.y1 if token.box else 0,
            token.box.x1 if token.box else 0,
        ),
    )
    text = " ".join(token.text.strip() for token in ordered if token.text.strip()).strip()
    weights = [max(len(token.text.strip()), 1) for token in ordered]
    confidence = sum(token.confidence * weight for token, weight in zip(ordered, weights, strict=True))
    confidence /= max(sum(weights), 1)
    return text, confidence


def _normalized_similarity(left: str, right: str) -> float:
    normalize = lambda value: "".join(char.lower() for char in value if char.isalnum())
    return SequenceMatcher(None, normalize(left), normalize(right)).ratio()




def _dash_confidence(crop: np.ndarray) -> float:
    """Detect a short horizontal missing-value marker without relying on OCR."""
    if crop.size == 0:
        return 0.0
    gray = crop if crop.ndim == 2 else cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    height, width = mask.shape[:2]
    if height < 4 or width < 8:
        return 0.0
    # Ignore table separators and crop boundaries.
    margin_x = max(2, round(width * 0.03))
    margin_y = max(2, round(height * 0.08))
    inner = mask[margin_y : height - margin_y, margin_x : width - margin_x]
    if inner.size == 0:
        return 0.0
    count, _, stats, centroids = cv2.connectedComponentsWithStats(inner, connectivity=8)
    best = 0.0
    for index in range(1, count):
        x, y, component_width, component_height, area = stats[index]
        if area < 2 or component_height <= 0:
            continue
        aspect = component_width / component_height
        if not (2.5 <= aspect <= 20.0):
            continue
        if component_width > inner.shape[1] * 0.55 or component_height > inner.shape[0] * 0.35:
            continue
        center_x, center_y = centroids[index]
        horizontal_center = abs(center_x - inner.shape[1] / 2) / max(inner.shape[1] / 2, 1)
        vertical_center = abs(center_y - inner.shape[0] / 2) / max(inner.shape[0] / 2, 1)
        if horizontal_center > 0.8 or vertical_center > 0.8:
            continue
        confidence = 0.75 + min(aspect / 40.0, 0.15)
        best = max(best, confidence)
    return float(min(best, 0.95))


def extract(
    image: np.ndarray,
    profile: Profile,
    engine: OCREngine,
    settings: ExtractionSettings,
) -> tuple[list[AnchorResult], list[FieldResult]]:
    height, width = image.shape[:2]
    anchor_results: list[AnchorResult] = []

    if settings.verify_anchors and profile.anchors:
        anchor_images: list[np.ndarray] = []
        anchor_boxes = []
        for anchor in profile.anchors:
            box = scale_box(
                anchor.roi,
                profile.reference_width,
                profile.reference_height,
                width,
                height,
            )
            anchor_boxes.append(box)
            crop = image[box.y1 : box.y2, box.x1 : box.x2]
            anchor_images.append(make_variants(crop, ["grayscale_upscale"], 3.0)[0][1])
        recognized = engine.recognize_many(anchor_images)
        for spec, box, tokens in zip(profile.anchors, anchor_boxes, recognized, strict=True):
            observed, _ = _join_tokens(tokens)
            similarity = _normalized_similarity(spec.expected, observed)
            anchor_results.append(
                AnchorResult(
                    name=spec.name,
                    expected=spec.expected,
                    observed=observed,
                    similarity=round(similarity, 4),
                    passed=similarity >= spec.minimum_similarity,
                    roi=box,
                )
            )

    jobs: list[tuple[int, str, np.ndarray, str | None]] = []
    scaled_boxes = []
    field_crops: list[np.ndarray] = []
    for field_index, spec in enumerate(profile.fields):
        box = scale_box(
            spec.roi,
            profile.reference_width,
            profile.reference_height,
            width,
            height,
        )
        box = box.padded(settings.padding_pixels).clamp(width, height)
        scaled_boxes.append(box)
        crop = image[box.y1 : box.y2, box.x1 : box.x2]
        field_crops.append(crop)
        for variant_name, variant_image in make_variants(
            crop,
            settings.variants,
            settings.upscale_factor,
        ):
            jobs.append((field_index, variant_name, variant_image, spec.whitelist))

    recognized_jobs = engine.recognize_many(
        [job[2] for job in jobs],
        [job[3] for job in jobs],
    )
    candidates_by_field: dict[int, list[OCRCandidate]] = {
        index: [] for index in range(len(profile.fields))
    }
    for job, tokens in zip(jobs, recognized_jobs, strict=True):
        field_index, variant_name, _, _ = job
        text, confidence = _join_tokens(tokens)
        candidate = evaluate_candidate(
            profile.fields[field_index],
            variant_name,
            text,
            confidence,
        )
        candidates_by_field[field_index].append(candidate)

    field_results: list[FieldResult] = []
    for index, spec in enumerate(profile.fields):
        if spec.allow_missing:
            dash_confidence = _dash_confidence(field_crops[index])
            if dash_confidence > 0:
                candidates_by_field[index].append(
                    evaluate_candidate(spec, "shape_dash_detector", "-", dash_confidence)
                )
        candidates = sorted(candidates_by_field[index], key=lambda item: item.score, reverse=True)
        best = candidates[0]
        accepted_missing = spec.allow_missing and best.value is None and best.text.strip() == "-"
        valid = bool(best.valid and (best.confidence >= settings.minimum_confidence or accepted_missing))
        reason = best.reason
        if best.valid and best.confidence < settings.minimum_confidence and not accepted_missing:
            reason = f"confidence_below_threshold:{settings.minimum_confidence}"
        field_results.append(
            FieldResult(
                key=spec.key,
                label=spec.label,
                raw_text=best.text,
                value=best.value,
                unit=best.unit,
                confidence=round(best.confidence, 4),
                valid=valid,
                reason=reason,
                roi=scaled_boxes[index],
                variant=best.variant,
                candidates=candidates,
            )
        )
    return anchor_results, field_results
