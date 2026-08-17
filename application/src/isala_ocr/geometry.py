from __future__ import annotations

from .models import Box


def scale_box(box: Box, reference_width: int, reference_height: int, width: int, height: int) -> Box:
    sx = width / reference_width
    sy = height / reference_height
    scaled = Box(
        round(box.x1 * sx),
        round(box.y1 * sy),
        round(box.x2 * sx),
        round(box.y2 * sy),
    )
    return scaled.clamp(width, height)
