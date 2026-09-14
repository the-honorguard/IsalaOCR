from __future__ import annotations

from typing import Iterable, Sequence

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


# intersection_area()/area()/union() were each implemented independently in
# training/mapping.py, training/mapping_ground_truth.py,
# training/generic_detection.py and training/dynamic_locator.py
# (CODE_REVIEW_v3.16.0.md, sectie Hoog: "Geometrie/IoU-berekeningen 4x
# onafhankelijk opnieuw geïmplementeerd"). Verified byte-identical in
# behavior before consolidating here (see
# documentation/architecture/refactor-phase2-plan.md, item 2) -- union()
# picked the explicit-empty-list-check variant (from generic_detection.py/
# dynamic_locator.py) as canonical over the bare min()/max() version that
# used to live in mapping_ground_truth.py, since that only changes what
# error an already-invalid call raises (a ValueError with a clear message
# instead of min()'s own "arg is an empty sequence"), not any in-range
# result.
#
# training/table_model_comparison.py's _iou/_box_area/_coverage_fraction
# work on plain (x1, y1, x2, y2) float tuples rather than Box, and use a
# 1e-9 epsilon guard instead of this module's clamp-to-1 -- a deliberate
# difference for a different (float, high-volume comparison) use case, not
# consolidated here without re-tuning the comparison thresholds that depend
# on it. See the refactor-phase2 plan for that trade-off.


def intersection_area(left: Box, right: Box) -> int:
    """Pixel-area overlap of two boxes (0 when they don't overlap)."""
    return max(0, min(left.x2, right.x2) - max(left.x1, right.x1)) * max(
        0, min(left.y2, right.y2) - max(left.y1, right.y1)
    )


def area(box: Box) -> int:
    """Pixel area of a box, clamped to at least 1 to keep ratios finite."""
    return max(1, box.width * box.height)


def union(boxes: Iterable[Box] | Sequence[Box]) -> Box:
    """Smallest box containing every box in ``boxes``.

    Raises ``ValueError`` on an empty sequence rather than propagating
    ``min()``'s own less specific error.
    """
    values = list(boxes)
    if not values:
        raise ValueError("Cannot union an empty box sequence")
    return Box(
        min(box.x1 for box in values),
        min(box.y1 for box in values),
        max(box.x2 for box in values),
        max(box.y2 for box in values),
    )
