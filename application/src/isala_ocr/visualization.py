from __future__ import annotations

import cv2
import numpy as np

from .models import AnchorResult, FieldResult


def draw_overlay(
    image: np.ndarray,
    anchors: list[AnchorResult],
    fields: list[FieldResult],
) -> np.ndarray:
    canvas = image.copy()
    for anchor in anchors:
        box = anchor.roi
        cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), (0, 255, 0), 1)
        text = f"anchor:{anchor.name} {anchor.similarity:.2f}"
        cv2.putText(canvas, text, (box.x1, max(12, box.y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    for field in fields:
        box = field.roi
        color = (0, 255, 0) if field.valid else (0, 0, 255)
        cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), color, 1)
        value = "missing" if field.value is None else str(field.value)
        text = f"{field.key}={value} {field.unit or ''} ({field.confidence:.2f})"
        cv2.putText(canvas, text, (box.x1, max(12, box.y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
    return canvas
