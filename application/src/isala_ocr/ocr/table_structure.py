from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from ..models import Box, OCRToken
from .paddle import PaddleEngine
from .paddlex_runtime import prepare_paddlex_runtime

TABLE_ENGINE_VERSION = "ppstructurev3-table-v3"


@dataclass(frozen=True)
class TableCell:
    table_id: str
    cell_id: str
    row_index: int
    column_index: int
    box: Box
    text: str
    confidence: float
    row_span: int = 1
    column_span: int = 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "cell_id": self.cell_id,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "row_span": self.row_span,
            "column_span": self.column_span,
            "text": self.text,
            "confidence": float(self.confidence),
            "x1": self.box.x1,
            "y1": self.box.y1,
            "x2": self.box.x2,
            "y2": self.box.y2,
        }


@dataclass(frozen=True)
class TableRegion:
    table_id: str
    box: Box
    confidence: float
    cells: tuple[TableCell, ...]
    html: str = ""
    excluded_boxes: tuple[Box, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "confidence": float(self.confidence),
            "x1": self.box.x1,
            "y1": self.box.y1,
            "x2": self.box.x2,
            "y2": self.box.y2,
            "html": self.html,
            "cells": [cell.as_dict() for cell in self.cells],
            "excluded_boxes": [box.to_list() for box in self.excluded_boxes],
        }


def _json_data(result: Any) -> dict[str, Any]:
    data = getattr(result, "json", result)
    if callable(data):
        data = data()
    if not isinstance(data, dict):
        return {}
    nested = data.get("res")
    return nested if isinstance(nested, dict) else data


def _box_from_any(value: Any) -> Box | None:
    if value is None:
        return None
    array = np.asarray(value)
    if array.size < 4:
        return None
    try:
        if array.ndim == 1 and array.size >= 4:
            values = [int(round(float(item))) for item in array[:4]]
            x1, y1, x2, y2 = values
        else:
            points = array.reshape(-1, 2)
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            x1, y1, x2, y2 = (
                int(math.floor(min(xs))), int(math.floor(min(ys))),
                int(math.ceil(max(xs))), int(math.ceil(max(ys))),
            )
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return Box(x1, y1, x2, y2)


def _center(box: Box) -> tuple[float, float]:
    return ((box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0)


def _box_union(boxes: Sequence[Box]) -> Box:
    return Box(
        min(box.x1 for box in boxes), min(box.y1 for box in boxes),
        max(box.x2 for box in boxes), max(box.y2 for box in boxes),
    )


def _inside(center: tuple[float, float], box: Box, guard: int = 2) -> bool:
    x, y = center
    return box.x1 - guard <= x <= box.x2 + guard and box.y1 - guard <= y <= box.y2 + guard




def _intersection_area(left: Box, right: Box) -> int:
    width = max(0, min(left.x2, right.x2) - max(left.x1, right.x1))
    height = max(0, min(left.y2, right.y2) - max(left.y1, right.y1))
    return width * height




def _box_iou(left: Box, right: Box) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / max(1, union)


def _panel_suggestions_from_variant_results(
    results: dict[str, list[TableRegion]], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    """Keep plausible table regions from *all* preprocessing variants.

    The structurally best full-image run is still used as detector output, but Panel
    Setup must not lose a second table merely because another contrast variant won
    the global benchmark. Suggestions are therefore deduplicated across variants.
    """
    candidates: list[dict[str, Any]] = []
    image_area = max(1, image_width * image_height)
    for variant, regions in results.items():
        for region in regions:
            box = region.box.clamp(image_width, image_height)
            area_fraction = (box.width * box.height) / image_area
            cell_count = len(region.cells)
            if box.width < 24 or box.height < 24 or area_fraction < 0.01 or area_fraction > 0.80:
                continue
            metrics = score_table_structure([region])
            score = float(metrics.get("score") or 0.0) + min(12.0, cell_count * 0.35)
            candidates.append({
                "box": box, "variant": variant, "score": score,
                "cell_count": cell_count, "confidence": float(region.confidence or 0.0),
                "excluded_boxes": tuple(region.excluded_boxes),
            })

    groups: list[dict[str, Any]] = []
    for item in sorted(candidates, key=lambda value: float(value["score"]), reverse=True):
        box = item["box"]
        matched = None
        for group in groups:
            rep = group["box"]
            overlap_smaller = _table_overlap_ratio(box, rep)
            if _box_iou(box, rep) >= 0.45 or overlap_smaller >= 0.80:
                matched = group
                break
        if matched is None:
            groups.append({
                "box": box, "best": item, "variants": {str(item["variant"])}, "support": 1,
            })
        else:
            matched["variants"].add(str(item["variant"]))
            matched["support"] += 1
            if float(item["score"]) > float(matched["best"]["score"]):
                matched["box"] = box
                matched["best"] = item

    suggestions: list[dict[str, Any]] = []
    for index, group in enumerate(groups[:12], start=1):
        box = group["box"]
        best = group["best"]
        excluded = tuple(best.get("excluded_boxes") or ())
        raw_boxes = (box, *excluded)
        suggestions.append({
            "suggestion_id": f"benchmark-{index}",
            "kind": "benchmark_table_region",
            "x1": box.x1, "y1": box.y1, "x2": box.x2, "y2": box.y2,
            "variant": str(best["variant"]),
            "support": int(group["support"]),
            "variants": sorted(group["variants"]),
            "cell_count": int(best["cell_count"]),
            "confidence": float(best["confidence"]),
            "score": round(float(best["score"]), 2),
            "raw_x1": min(item.x1 for item in raw_boxes), "raw_y1": min(item.y1 for item in raw_boxes),
            "raw_x2": max(item.x2 for item in raw_boxes), "raw_y2": max(item.y2 for item in raw_boxes),
            "excluded_boxes": [item.to_list() for item in excluded],
        })
    return suggestions


def _assign_tokens_to_cells(tokens: Sequence[OCRToken], cell_boxes: Sequence[Box]) -> dict[int, list[OCRToken]]:
    """Assign every OCR token to at most one cell using geometric overlap.

    Centre-only assignment duplicates text when Paddle cell boxes overlap and can
    miss slightly shifted OCR boxes. Token coverage is the primary signal; the
    centre point is only a small tie-breaker.
    """
    assigned: dict[int, list[OCRToken]] = {index: [] for index in range(len(cell_boxes))}
    for token in tokens:
        if token.box is None or not str(token.text or "").strip():
            continue
        token_area = max(1, token.box.width * token.box.height)
        best_index: int | None = None
        best_score = 0.0
        center = _center(token.box)
        for index, cell_box in enumerate(cell_boxes):
            intersection = _intersection_area(token.box, cell_box)
            coverage = intersection / token_area
            center_inside = _inside(center, cell_box, guard=2)
            if coverage < 0.30 and not center_inside:
                continue
            cell_area = max(1, cell_box.width * cell_box.height)
            cell_coverage = intersection / cell_area
            score = 0.75 * coverage + 0.10 * min(1.0, cell_coverage) + (0.15 if center_inside else 0.0)
            if score > best_score:
                best_index = index
                best_score = score
        if best_index is not None:
            assigned[best_index].append(token)
    return assigned

def _weighted_text(tokens: Sequence[OCRToken]) -> tuple[str, float]:
    ordered = sorted(
        (token for token in tokens if token.box is not None and str(token.text or "").strip()),
        key=lambda token: (token.box.x1, token.box.y1),
    )
    if not ordered:
        return "", 0.0
    text = " ".join(str(token.text).strip() for token in ordered)
    weights = [max(1, len(str(token.text).strip())) for token in ordered]
    confidence = sum(float(token.confidence) * weight for token, weight in zip(ordered, weights, strict=True)) / sum(weights)
    return text, confidence


def _tokens_from_table_ocr(table: dict[str, Any]) -> list[OCRToken]:
    ocr = table.get("table_ocr_pred")
    if not isinstance(ocr, dict):
        return []
    texts = list(ocr.get("rec_texts") or [])
    scores = list(ocr.get("rec_scores") or [])
    boxes = list(ocr.get("rec_boxes") or ocr.get("rec_polys") or [])
    tokens: list[OCRToken] = []
    for index, text in enumerate(texts):
        box = _box_from_any(boxes[index]) if index < len(boxes) else None
        score = float(scores[index]) if index < len(scores) else 0.0
        if box is not None and str(text or "").strip():
            tokens.append(OCRToken(str(text), score, box))
    return tokens


def _cluster_rows(cell_boxes: Sequence[Box]) -> list[list[int]]:
    if not cell_boxes:
        return []
    heights = sorted(max(1, box.height) for box in cell_boxes)
    median_height = heights[len(heights) // 2]
    tolerance = max(4.0, median_height * 0.55)
    indices = sorted(range(len(cell_boxes)), key=lambda idx: (_center(cell_boxes[idx])[1], cell_boxes[idx].x1))
    rows: list[list[int]] = []
    row_centers: list[float] = []
    for index in indices:
        cy = _center(cell_boxes[index])[1]
        best = None
        best_distance = float("inf")
        for row_index, center in enumerate(row_centers):
            distance = abs(cy - center)
            if distance <= tolerance and distance < best_distance:
                best = row_index
                best_distance = distance
        if best is None:
            rows.append([index])
            row_centers.append(cy)
        else:
            rows[best].append(index)
            row_centers[best] = sum(_center(cell_boxes[idx])[1] for idx in rows[best]) / len(rows[best])
    ordered_rows = sorted(zip(row_centers, rows), key=lambda item: item[0])
    return [sorted(row, key=lambda idx: cell_boxes[idx].x1) for _, row in ordered_rows]


def _remove_terminal_full_width_noise(
    cell_boxes: Sequence[Box], rows: Sequence[Sequence[int]],
) -> list[list[int]]:
    """Drop a likely non-table footer accidentally returned as the last row."""
    cleaned = [list(row) for row in rows]
    if len(cleaned) < 3 or not cleaned[-1] or len(cleaned[-1]) != 1:
        return cleaned
    row_counts = [len(row) for row in cleaned if row]
    multi_counts = [count for count in row_counts if count >= 2]
    if len(multi_counts) < 2:
        return cleaned
    from collections import Counter
    if Counter(multi_counts).most_common(1)[0][0] < 2:
        return cleaned

    widths = sorted(max(1, box.width) for box in cell_boxes)
    median_width = widths[len(widths) // 2]
    footer = cell_boxes[cleaned[-1][0]]
    table_left = min(cell_boxes[index].x1 for row in cleaned[:-1] for index in row)
    table_right = max(cell_boxes[index].x2 for row in cleaned[:-1] for index in row)
    edge_tolerance = max(6, median_width * 0.12)
    spans_table = footer.x1 <= table_left + edge_tolerance and footer.x2 >= table_right - edge_tolerance
    if footer.width >= median_width * 1.8 and spans_table:
        cleaned.pop()
    return cleaned


def _cluster_centers(values: Sequence[float], tolerance: float) -> list[list[int]]:
    """Cluster numeric center positions into ordered raster lines."""
    groups: list[list[int]] = []
    centers: list[float] = []
    for index in sorted(range(len(values)), key=lambda item: values[item]):
        value = float(values[index])
        nearest = min(range(len(centers)), key=lambda item: abs(centers[item] - value), default=-1)
        if nearest < 0 or abs(centers[nearest] - value) > tolerance:
            groups.append([index])
            centers.append(value)
        else:
            groups[nearest].append(index)
            centers[nearest] = sum(float(values[item]) for item in groups[nearest]) / len(groups[nearest])
    return [group for _, group in sorted(zip(centers, groups), key=lambda item: item[0])]


def _global_column_layout(
    cell_boxes: Sequence[Box], rows: Sequence[Sequence[int]],
) -> dict[int, tuple[int, int]]:
    """Assign cells to one shared column grid for the whole table.

    PP-Structure returns cell boxes, but its boxes do not always contain stable
    row/column indexes.  Numbering cells independently inside every row makes
    a missing cell shift all following columns.  We therefore cluster the left
    edges across all rows and use those anchors as the table's global columns.
    A wide box covering multiple anchors is represented with ``column_span``.
    This is geometry-only and deliberately does not depend on report-specific
    coordinates or text labels.
    """
    if not cell_boxes:
        return {}

    widths = sorted(max(1, box.width) for box in cell_boxes)
    # A missing cell changes its row's centres, but it does not change the
    # left edge of the next real column. Build the shared raster from left
    # edges so sparse rows cannot shift later columns to the left.
    tolerance = max(6.0, min(40.0, widths[len(widths) // 2] * 0.20))
    left_edges = [float(box.x1) for box in cell_boxes]
    columns = _cluster_centers(left_edges, tolerance)
    anchors = [
        sum(left_edges[index] for index in column) / len(column)
        for column in columns
    ]
    gaps = [right - left for left, right in zip(anchors, anchors[1:]) if right > left]
    column_gap = sorted(gaps)[len(gaps) // 2] if gaps else None
    result: dict[int, tuple[int, int]] = {}
    for index, box in enumerate(cell_boxes):
        column_index = min(range(len(anchors)), key=lambda item: abs(anchors[item] - box.x1))
        span = 1
        if column_gap:
            span = max(1, int(round((box.x2 - anchors[column_index]) / column_gap)))
        result[index] = (column_index, span)
    return result


def parse_ppstructure_tables(
    data: dict[str, Any],
    *,
    source_id: str,
    fallback_tokens: Sequence[OCRToken] = (),
    image_width: int | None = None,
    image_height: int | None = None,
) -> list[TableRegion]:
    """Convert PP-StructureV3 output to stable table/cell records.

    Paddle supplies the cell geometry. Row/column indexes are reconstructed from
    that geometry. Full-page OCR is preferred for cell text so recognition stays
    consistent with the rest of IsalaOCR; when it has no token for a particular
    cell, PP-Structure's own table OCR is used for that cell only.
    """
    raw_tables = data.get("table_res_list") or []
    if not isinstance(raw_tables, list):
        return []
    regions: list[TableRegion] = []
    for table_index, raw in enumerate(raw_tables):
        if not isinstance(raw, dict):
            continue
        raw_cells = list(raw.get("cell_box_list") or raw.get("bbox") or [])
        boxes = [box for value in raw_cells if (box := _box_from_any(value)) is not None]
        if len(boxes) < 4:
            continue
        if image_width is not None and image_height is not None:
            boxes = [box.clamp(image_width, image_height) for box in boxes]
        raw_rows = _cluster_rows(boxes)
        rows = _remove_terminal_full_width_noise(boxes, raw_rows)
        if len(rows) < 2 or max((len(row) for row in rows), default=0) < 2:
            continue
        retained_indices = [index for row in rows for index in row]
        excluded_indices = [index for row in raw_rows for index in row if index not in retained_indices]
        union = _box_union([boxes[index] for index in retained_indices])
        signature = f"{source_id}|{table_index}|{union.to_list()}".encode("utf-8")
        table_id = hashlib.sha256(signature).hexdigest()[:24]

        # Assign each token to one best-fitting cell. This avoids duplicated text
        # when adjacent Paddle cells overlap by a few pixels. A per-cell fallback
        # to PP-Structure OCR prevents otherwise empty cells when the full-page OCR
        # misses a region.
        primary_tokens = list(fallback_tokens)
        internal_tokens = _tokens_from_table_ocr(raw)
        primary_by_cell = _assign_tokens_to_cells(primary_tokens, boxes)
        internal_by_cell = _assign_tokens_to_cells(internal_tokens, boxes)

        score = raw.get("structure_score")
        if score is None:
            score = raw.get("table_score")
        if score is None:
            score = 0.85
        global_columns = _global_column_layout(boxes, rows)
        cells: list[TableCell] = []
        for row_index, row in enumerate(rows):
            for box_index in row:
                box = boxes[box_index]
                column_index, column_span = global_columns.get(box_index, (0, 1))
                in_cell = primary_by_cell.get(box_index) or internal_by_cell.get(box_index) or []
                text, confidence = _weighted_text(in_cell)
                cell_id = hashlib.sha256(
                    f"{table_id}|{row_index}|{column_index}|{box.to_list()}".encode("utf-8")
                ).hexdigest()[:28]
                cells.append(
                    TableCell(
                        table_id=table_id,
                        cell_id=cell_id,
                        row_index=row_index,
                        column_index=column_index,
                        box=box,
                        text=text,
                        confidence=confidence,
                        column_span=column_span,
                    )
                )
        regions.append(
            TableRegion(
                table_id=table_id,
                box=union,
                confidence=float(score or 0.0),
                cells=tuple(cells),
                html=str(raw.get("pred_html") or ""),
                excluded_boxes=tuple(boxes[index] for index in excluded_indices),
            )
        )
    return regions


def _preprocess_table_image(image: np.ndarray, variant: str) -> np.ndarray:
    """Create conservative preprocessing variants for dark GUI-style tables.

    Every variant keeps the same pixel geometry so detected boxes remain directly
    comparable. The benchmark intentionally avoids destructive morphology; the
    goal is to learn whether contrast polarity is the limiting factor before any
    table model is fine-tuned.
    """
    import cv2

    if variant == "original":
        return image.copy()
    if image.ndim == 2:
        gray = image.copy()
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if variant == "grayscale":
        prepared = gray
    elif variant == "clahe":
        prepared = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    elif variant == "invert_clahe":
        enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        prepared = cv2.bitwise_not(enhanced)
    elif variant == "adaptive":
        enhanced = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(gray)
        min_dim = min(enhanced.shape[:2])
        block_size = min(31, min_dim if min_dim % 2 == 1 else min_dim - 1)
        if block_size >= 3:
            prepared = cv2.adaptiveThreshold(
                enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, 7
            )
        else:
            _, prepared = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        raise ValueError(f"Unknown table preprocessing variant: {variant}")
    return cv2.cvtColor(prepared, cv2.COLOR_GRAY2BGR)


def _table_overlap_ratio(left: Box, right: Box) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    smaller = max(1, min(left.width * left.height, right.width * right.height))
    return intersection / smaller


def _translate_table_regions(regions: Sequence[TableRegion], dx: int, dy: int) -> list[TableRegion]:
    if dx == 0 and dy == 0:
        return list(regions)
    translated: list[TableRegion] = []
    for region in regions:
        region_box = Box(region.box.x1 + dx, region.box.y1 + dy, region.box.x2 + dx, region.box.y2 + dy)
        cells = tuple(
            TableCell(
                table_id=cell.table_id, cell_id=cell.cell_id, row_index=cell.row_index,
                column_index=cell.column_index,
                box=Box(cell.box.x1 + dx, cell.box.y1 + dy, cell.box.x2 + dx, cell.box.y2 + dy),
                text=cell.text, confidence=cell.confidence, row_span=cell.row_span, column_span=cell.column_span,
            )
            for cell in region.cells
        )
        excluded = tuple(Box(box.x1 + dx, box.y1 + dy, box.x2 + dx, box.y2 + dy) for box in region.excluded_boxes)
        translated.append(TableRegion(region.table_id, region_box, region.confidence, cells, region.html, excluded))
    return translated


def _panel_crop_from_regions(regions: Sequence[TableRegion], image_width: int, image_height: int) -> Box | None:
    if not regions:
        return None
    union = _box_union([region.box for region in regions]).clamp(image_width, image_height)
    image_area = max(1, image_width * image_height)
    fraction = (union.width * union.height) / image_area
    # Do not trust a tiny accidental table or a region that is effectively the whole screenshot.
    if fraction < 0.06 or fraction > 0.82:
        return None
    pad_x = max(8, int(round(union.width * 0.06)))
    pad_y = max(8, int(round(union.height * 0.05)))
    return Box(union.x1 - pad_x, union.y1 - pad_y, union.x2 + pad_x, union.y2 + pad_y).clamp(image_width, image_height)


def _detect_soft_row_boundaries(gray: np.ndarray, box: Box, *, min_gap: int = 10) -> list[int]:
    """Find y-coordinates with a subtle but consistent contrast step between rows.

    Looks only at the mean row intensity inside ``box``: a real row boundary in
    these screenshots usually shows up as a small, consistent shift (alternating
    row shading) rather than a hard printed line. Steps far below the local
    noise floor are ignored (nothing there), and steps at the very top of the
    distribution are ignored too (already an obvious edge the detector would
    have found on its own) - this targets exactly the "too faint to notice"
    middle ground.
    """
    region = gray[box.y1:box.y2, box.x1:box.x2]
    if region.size == 0 or region.shape[0] < 6:
        return []
    row_means = region.astype(np.float32).mean(axis=1)
    kernel = np.ones(3, dtype=np.float32) / 3.0
    smoothed = np.convolve(row_means, kernel, mode="same")
    diffs = np.abs(np.diff(smoothed))
    if diffs.size == 0:
        return []
    noise_floor = float(diffs.std()) * 1.5
    hard_edge = float(np.percentile(diffs, 98))
    if hard_edge <= noise_floor:
        return []
    boundaries: list[int] = []
    last_index = -min_gap
    for index, value in enumerate(diffs):
        absolute_y = index + box.y1
        if (
            noise_floor < value < hard_edge
            and (index - last_index) >= min_gap
            and absolute_y >= box.y1 + min_gap
            and absolute_y <= box.y2 - min_gap
        ):
            boundaries.append(absolute_y)
            last_index = index
    return boundaries


def _draw_row_separator_lines(image: np.ndarray, boundary_ys: Sequence[int], box: Box) -> np.ndarray:
    """Draw hard separator lines used as input for the second detection pass."""
    import cv2

    canvas = image.copy()
    if not boundary_ys:
        return canvas
    gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY) if canvas.ndim == 3 else canvas
    # Light line on a dark UI, dark line on a light one, so it reads as a
    # gridline rather than noise regardless of the screenshot's theme.
    color = (255, 255, 255) if float(gray.mean()) < 128 else (0, 0, 0)
    for y in boundary_ys:
        # A crisp two-pixel rule survives the detector's own preprocessing
        # better than a one-pixel anti-aliased hint and is still narrow enough
        # not to become a cell in its own right.
        cv2.line(canvas, (box.x1, y), (box.x2, y), color, 2, cv2.LINE_8)
    return canvas


def score_table_structure(regions: Sequence[TableRegion]) -> dict[str, float | int]:
    """Score table output using geometry only, never recognized text.

    The score is deliberately heuristic and advisory. It rewards repeated rows,
    stable column positions and non-overlapping cells, which are the properties
    needed by the later row/column reconstruction stage.
    """
    cells = [cell for region in regions for cell in region.cells]
    if not cells:
        return {
            "score": 0.0, "table_count": 0, "cell_count": 0, "row_count": 0,
            "multi_cell_rows": 0, "row_regularity": 0.0, "column_alignment": 0.0,
            "column_width_consistency": 0.0, "overlap_penalty": 0.0,
        }
    row_count = 0
    multi_rows = 0
    row_regularity_parts: list[float] = []
    column_alignment_parts: list[float] = []
    column_width_consistency_parts: list[float] = []
    overlap_pairs = 0
    overlap_bad = 0
    for region in regions:
        rows: dict[int, list[TableCell]] = {}
        for cell in region.cells:
            rows.setdefault(int(cell.row_index), []).append(cell)
        row_count += len(rows)
        multi_rows += sum(1 for items in rows.values() if len(items) >= 2)
        counts = [len(items) for items in rows.values() if items]
        if counts:
            from collections import Counter
            mode_count = Counter(counts).most_common(1)[0][0]
            row_regularity_parts.append(sum(1 for count in counts if count == mode_count) / len(counts))
        columns: dict[int, list[TableCell]] = {}
        for cell in region.cells:
            columns.setdefault(int(cell.column_index), []).append(cell)
        for items in columns.values():
            if len(items) < 2:
                continue
            centers = [(_center(cell.box)[0]) for cell in items]
            widths = [max(1, cell.box.width) for cell in items]
            span = max(1.0, sum(widths) / len(widths))
            mean = sum(centers) / len(centers)
            deviation = sum(abs(value - mean) for value in centers) / len(centers)
            column_alignment_parts.append(max(0.0, 1.0 - min(1.0, deviation / span)))
            width_mean = sum(widths) / len(widths)
            width_deviation = sum(abs(value - width_mean) for value in widths) / len(widths)
            column_width_consistency_parts.append(
                max(0.0, 1.0 - min(1.0, width_deviation / max(1.0, width_mean)))
            )
        region_cells = list(region.cells)
        for i, left in enumerate(region_cells):
            for right in region_cells[i + 1:]:
                if left.row_index != right.row_index:
                    continue
                overlap_pairs += 1
                if _table_overlap_ratio(left.box, right.box) > 0.35:
                    overlap_bad += 1
    row_regularity = sum(row_regularity_parts) / len(row_regularity_parts) if row_regularity_parts else 0.0
    column_alignment = sum(column_alignment_parts) / len(column_alignment_parts) if column_alignment_parts else 0.0
    column_width_consistency = (
        sum(column_width_consistency_parts) / len(column_width_consistency_parts)
        if column_width_consistency_parts else 0.0
    )
    overlap_penalty = overlap_bad / overlap_pairs if overlap_pairs else 0.0
    row_density = min(1.0, multi_rows / max(1.0, row_count * 0.75))
    cell_density = min(1.0, len(cells) / 30.0)
    confidence = sum(float(region.confidence or 0.0) for region in regions) / max(1, len(regions))
    score = 100.0 * (
        0.27 * row_density
        + 0.23 * row_regularity
        + 0.23 * column_alignment
        + 0.15 * cell_density
        + 0.12 * max(0.0, min(1.0, confidence))
        - 0.20 * overlap_penalty
    )
    return {
        "score": round(max(0.0, score), 2),
        "table_count": len(regions),
        "cell_count": len(cells),
        "row_count": row_count,
        "multi_cell_rows": multi_rows,
        "row_regularity": round(row_regularity, 4),
        "column_alignment": round(column_alignment, 4),
        "column_width_consistency": round(column_width_consistency, 4),
        "overlap_penalty": round(overlap_penalty, 4),
    }


def draw_cell_overlay(image: np.ndarray, regions: Sequence[Any]) -> np.ndarray:
    """Draw table-region and cell boxes on a copy of ``image`` for visual review.

    Shared between the Detectie-lab CLI runner and anything else that needs to
    render the same overlay, so the drawing logic (colors, line widths) stays
    in one place instead of being duplicated per caller.
    """
    import cv2

    canvas = image.copy()
    for region in regions:
        box = region.box
        cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), (0, 140, 255), 2)
        for cell in region.cells:
            cbox = cell.box
            cv2.rectangle(canvas, (cbox.x1, cbox.y1), (cbox.x2, cbox.y2), (0, 220, 0), 1)
    return canvas


class PPStructureTableEngine:
    """Lazy PP-StructureV3 wrapper used only for table/layout geometry."""

    def __init__(self, settings: dict[str, Any], table_settings: dict[str, Any] | None = None):
        self.settings = dict(settings)
        self.table_settings = dict(table_settings or {})
        self._pipeline = None
        self._region_model = None
        self._version = "unknown"
        self._load_error: Exception | None = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        if self._load_error is not None:
            raise RuntimeError("PP-StructureV3 initialization previously failed") from self._load_error
        prepare_paddlex_runtime(self.settings)
        try:
            import paddleocr
            from paddleocr import PPStructureV3
        except Exception as exc:
            self._load_error = exc
            raise RuntimeError("PP-StructureV3 is unavailable in the installed PaddleOCR package") from exc
        self._version = getattr(paddleocr, "__version__", "unknown")
        kwargs: dict[str, Any] = {
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_seal_recognition": False,
            "use_table_recognition": True,
            "use_formula_recognition": False,
            "use_chart_recognition": False,
            "use_region_detection": True,
            "device": str(self.settings.get("device", "cpu")),
            "engine": self.settings.get("inference_engine", "paddle_static"),
        }
        passthrough = {
            "layout_detection_model_name": "layout_detection_model",
            "table_classification_model_name": "table_classification_model",
            "wired_table_structure_recognition_model_name": "wired_structure_model",
            "wireless_table_structure_recognition_model_name": "wireless_structure_model",
            "wired_table_cells_detection_model_name": "wired_cells_model",
            "wireless_table_cells_detection_model_name": "wireless_cells_model",
            "wired_table_cells_detection_model_dir": "wired_cells_model_dir",
            "wireless_table_cells_detection_model_dir": "wireless_cells_model_dir",
        }
        for paddle_key, config_key in passthrough.items():
            value = self.table_settings.get(config_key)
            if value:
                kwargs[paddle_key] = value
        try:
            self._pipeline = PPStructureV3(**kwargs)
        except Exception as exc:
            self._load_error = exc
            message = str(exc)
            if "dependency error occurred during pipeline creation" in message.lower():
                raise RuntimeError(
                    "PP-StructureV3 could not start because its document-parser dependencies "
                    "are unavailable. The runtime image must include the PaddleOCR "
                    "'doc-parser' extra (paddleocr[doc-parser]==3.7.0). Open Stap 1 · Voorbereiding and rebuild the runtime/model cache "
                    "with the current release."
                ) from exc
            raise
        return self._pipeline

    def warmup(self) -> None:
        self._load()

    def _load_region_model(self):
        """Load the optional learned full-page table-region detector."""
        model_dir = str(self.table_settings.get("table_region_model_dir") or "").strip()
        if not model_dir:
            return None
        if self._region_model is not None:
            return self._region_model
        try:
            from paddlex import create_model
            self._region_model = create_model(
                model_name="PicoDet-S", model_dir=model_dir,
                device=str(self.settings.get("device", "cpu")),
            )
        except Exception as exc:
            raise RuntimeError(f"Tabelregio-detector kon niet worden geladen: {model_dir}") from exc
        return self._region_model

    def _trained_region_boxes(self, image: np.ndarray) -> list[tuple[Box, float]]:
        model = self._load_region_model()
        if model is None:
            return []
        threshold = float(self.table_settings.get("table_region_model_threshold", 0.25) or 0.25)
        boxes: list[tuple[Box, float]] = []
        for result in model.predict(PaddleEngine._prepare_image(image), batch_size=1, threshold=threshold):
            data = _json_data(result)
            raw_boxes = data.get("boxes") if isinstance(data, dict) else None
            if not isinstance(raw_boxes, list):
                continue
            for item in raw_boxes:
                if not isinstance(item, dict):
                    continue
                coordinates = item.get("coordinate") or item.get("bbox") or item.get("box")
                if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 4:
                    continue
                try:
                    box = Box(*(int(round(float(value))) for value in coordinates))
                    score = float(item.get("score") or item.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    continue
                if box.x2 > box.x1 and box.y2 > box.y1:
                    boxes.append((box, max(0.0, min(1.0, score))))
        return boxes

    def detect_with_trained_regions(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Use the learned table-region detector before PP-Structure cell parsing."""
        height, width = image.shape[:2]
        regions: list[TableRegion] = []
        region_boxes = self._trained_region_boxes(image)
        for index, (box, score) in enumerate(region_boxes, start=1):
            box = box.clamp(width, height)
            if box.width < 20 or box.height < 20:
                continue
            crop = image[box.y1:box.y2, box.x1:box.x2]
            local = self._detect_once(crop, source_id=f"{source_id}:table-region-{index}", fallback_tokens=fallback_tokens)
            regions.extend(_translate_table_regions(local, box.x1, box.y1))
        return regions, {
            "enabled": True,
            "mode": "trained_table_regions",
            "region_count": len(region_boxes),
            "cell_count": sum(len(region.cells) for region in regions),
            "model_threshold": float(self.table_settings.get("table_region_model_threshold", 0.25) or 0.25),
        }

    def detect_with_trained_regions_benchmark(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Trained-region boxes, but with a preprocessing-variant trial per box.

        ``detect_with_trained_regions`` does a single un-preprocessed pass per
        region, which is what removed the contrast/polarity benchmark once a
        region model was activated. This keeps the trained region boxes (still
        the most reliable way to find the table panel itself) but restores the
        per-region variant trial, mirroring ``detect_panels_with_benchmark``.
        Used only by the temporary detection-lab comparison tool ("Probeer 2").
        """
        height, width = image.shape[:2]
        variants = self.table_settings.get("preprocessing_variants") or [
            "original", "grayscale", "clahe", "invert_clahe", "adaptive"
        ]
        allowed = {"original", "grayscale", "clahe", "invert_clahe", "adaptive"}
        variants = [str(item) for item in variants if str(item) in allowed]
        if "original" not in variants:
            variants.insert(0, "original")

        all_regions: list[TableRegion] = []
        region_results: list[dict[str, Any]] = []
        all_runs: list[dict[str, Any]] = []
        region_boxes = self._trained_region_boxes(image)
        for index, (box, _score) in enumerate(region_boxes, start=1):
            box = box.clamp(width, height)
            if box.width < 20 or box.height < 20:
                continue
            crop = image[box.y1:box.y2, box.x1:box.x2]
            best_regions: list[TableRegion] = []
            best_score = -1.0
            best_variant = "original"
            for variant in variants:
                prepared = _preprocess_table_image(crop, variant)
                local_source_id = f"{source_id}:table-region-{index}"
                local_regions = self._detect_once(
                    prepared, source_id=local_source_id,
                    fallback_tokens=fallback_tokens if variant == "original" else (),
                )
                translated = _translate_table_regions(local_regions, box.x1, box.y1)
                metrics = score_table_structure(translated)
                run = {"region_index": index, "variant": variant, "scope": "trained_region", "region_box": box.to_list(), **metrics}
                all_runs.append(run)
                numeric_score = float(metrics.get("score") or 0.0)
                if numeric_score > best_score:
                    best_regions = translated
                    best_score = numeric_score
                    best_variant = variant
            all_regions.extend(best_regions)
            region_results.append({
                "region_index": index, "region_box": box.to_list(),
                "selected_variant": best_variant,
                "selected_score": round(max(0.0, best_score), 2),
                "cell_count": sum(len(region.cells) for region in best_regions),
            })
        selected_score = (
            sum(float(item["selected_score"]) for item in region_results) / len(region_results)
            if region_results else 0.0
        )
        return all_regions, {
            "enabled": True,
            "mode": "trained_table_regions_benchmark",
            "selected_variant": "per-region",
            "selected_score": round(selected_score, 2),
            "region_count": len(region_results),
            "regions": region_results,
            "runs": all_runs,
            "model_threshold": float(self.table_settings.get("table_region_model_threshold", 0.25) or 0.25),
            "selection_rule": "best preprocessing variant per trained table-region box",
        }

    def detect_with_contrast_lines(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Find faint row-to-row contrast steps and reinforce them as a hard line.

        Idea: alternating-row shading in the source screenshots is often too
        subtle for PP-Structure's line/edge model to separate into distinct
        rows, which is one plausible explanation for cells merging across a
        row boundary. This scans the mean row intensity inside the likely
        table panel for small-but-consistent steps (above sensor noise, below
        an already-obvious gridline) and draws a 1px separator at each one
        before running detection once on the result. Used only by the
        temporary detection-lab comparison tool ("Probeer 3").
        """
        import cv2

        height, width = image.shape[:2]
        baseline_regions = self._detect_once(image, source_id=source_id, fallback_tokens=fallback_tokens)
        panel_box = _panel_crop_from_regions(baseline_regions, width, height)
        if panel_box is None:
            panel_box = Box(0, 0, width, height)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        # Detect within each existing table region, not across the union of
        # the whole screenshot.  The gap between tables and adjacent echo/
        # graph content otherwise creates convincing-looking but false lines.
        scan_boxes = [region.box.clamp(width, height) for region in baseline_regions] or [panel_box]
        boundary_ys = sorted({
            y for scan_box in scan_boxes
            for y in _detect_soft_row_boundaries(gray, scan_box)
        })
        augmented = _draw_row_separator_lines(image, boundary_ys, panel_box)
        regions = self._detect_once(augmented, source_id=source_id, fallback_tokens=fallback_tokens)
        metrics = score_table_structure(regions)
        return regions, {
            "enabled": True,
            "mode": "contrast_row_lines",
            "panel_box": panel_box.to_list(),
            "scan_boxes": [scan_box.to_list() for scan_box in scan_boxes],
            "lines_drawn": len(boundary_ys),
            "line_positions": boundary_ys,
            **metrics,
        }

    def detect_with_hybrid_benchmark(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = (),
        base_regions: Sequence[TableRegion] | None = None,
        alternate_regions: Sequence[TableRegion] | None = None,
        allow_cross_column: bool = False,
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Keep full-benchmark geometry, borrowing only clear splits from regions.

        The full benchmark is the authority for column widths.  A trained-region
        pass may replace one unusually tall cell only when two or more of its
        cells fit inside that cell and together cover most of its height.
        """
        base_meta: dict[str, Any] = {"selection_rule": "cached full benchmark"}
        if base_regions is None:
            base, base_meta = self.detect_with_forced_full_benchmark(
                image, source_id=source_id, fallback_tokens=fallback_tokens
            )
        else:
            base = list(base_regions)
        if alternate_regions is None:
            alternate, _ = self.detect_with_trained_regions_benchmark(
                image, source_id=source_id, fallback_tokens=fallback_tokens
            )
        else:
            alternate = list(alternate_regions)
        replacements = 0
        merged: list[TableRegion] = []
        for region in base:
            candidates = [item for item in alternate if _box_iou(region.box, item.box) >= 0.35]
            alt_cells = [cell for item in candidates for cell in item.cells]
            cells: list[TableCell] = []
            for cell in region.cells:
                splits = [
                    other for other in alt_cells
                    if (allow_cross_column or other.column_index == cell.column_index)
                    and _inside(_center(other.box), cell.box, guard=3)
                    and _intersection_area(cell.box, other.box) / max(1, cell.box.height * other.box.height) >= 0.65
                    and _intersection_area(cell.box, other.box) / max(1, other.box.width * other.box.height) >= 0.65
                ]
                if len(splits) < 2:
                    cells.append(cell)
                    continue
                splits.sort(key=lambda item: item.box.y1)
                covered = _box_union([item.box for item in splits])
                coverage = _intersection_area(cell.box, covered) / max(1, cell.box.width * cell.box.height)
                if coverage < 0.65 or covered.height < cell.box.height * 0.75:
                    cells.append(cell)
                    continue
                cells.extend(splits)
                replacements += 1
            merged.append(TableRegion(region.table_id, region.box, region.confidence, tuple(cells), region.html, region.excluded_boxes))
        return merged, {
            "enabled": True, "mode": "hybrid_full_benchmark_with_region_splits",
            "split_replacements": replacements, **base_meta,
        }

    def _detect_once(self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()) -> list[TableRegion]:
        pipeline = self._load()
        prepared = PaddleEngine._prepare_image(image)
        results = list(
            pipeline.predict(
                prepared,
                use_table_orientation_classify=False,
                # This pass learns table/cell geometry only. Asking PaddleX to
                # merge OCR results here can dereference general_ocr_pipeline
                # when that optional pipeline is absent on otherwise valid
                # table images. Semantic OCR matching happens separately.
                use_ocr_results_with_table_cells=False,
                use_e2e_wireless_table_rec_model=False,
                use_e2e_wired_table_rec_model=False,
            )
        )
        if not results:
            return []
        data = _json_data(results[0])
        height, width = prepared.shape[:2]
        return parse_ppstructure_tables(
            data, source_id=source_id, fallback_tokens=fallback_tokens,
            image_width=width, image_height=height,
        )

    def detect_with_benchmark(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Run several geometry-preserving preprocessing variants and select the best.

        Selection uses only structural geometry, so OCR text cannot accidentally
        bias localization. The original image always participates and therefore
        remains the safe fallback when contrast preprocessing hurts.
        """
        if str(self.table_settings.get("table_region_model_dir") or "").strip():
            return self.detect_with_trained_regions(image, source_id=source_id, fallback_tokens=fallback_tokens)
        return self._benchmark_full_image(image, source_id=source_id, fallback_tokens=fallback_tokens)

    def detect_with_forced_full_benchmark(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Always run the full preprocessing-variant benchmark, ignoring an active
        trained table-region model.

        Used only by the temporary detection-lab comparison tool ("Probeer 1")
        to test whether the contrast/polarity variant trial still helps once a
        trained region model has taken over ``detect_with_benchmark``. Not part
        of the regular detection pipeline.
        """
        return self._benchmark_full_image(image, source_id=source_id, fallback_tokens=fallback_tokens)

    def _benchmark_full_image(
        self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        variants = self.table_settings.get("preprocessing_variants") or [
            "original", "grayscale", "clahe", "invert_clahe", "adaptive"
        ]
        allowed = {"original", "grayscale", "clahe", "invert_clahe", "adaptive"}
        variants = [str(item) for item in variants if str(item) in allowed]
        if "original" not in variants:
            variants.insert(0, "original")
        runs: list[dict[str, Any]] = []
        best_regions: list[TableRegion] = []
        best_score = -1.0
        best_variant = "original"
        best_scope = "full"

        # Benchmark every preprocessing variant on the full screenshot first.
        # This lets a contrast variant discover a table that the untouched image
        # missed; cropping is therefore never based solely on the weakest pass.
        full_results: dict[str, list[TableRegion]] = {}
        for variant in variants:
            prepared = _preprocess_table_image(image, variant)
            regions = self._detect_once(prepared, source_id=source_id, fallback_tokens=fallback_tokens if variant == "original" else ())
            full_results[variant] = regions
            metrics = score_table_structure(regions)
            runs.append({"variant": variant, "scope": "full", **metrics})
            numeric_score = float(metrics.get("score") or 0.0)
            if numeric_score > best_score:
                best_regions = regions
                best_score = numeric_score
                best_variant = variant
                best_scope = "full"

        # A second pass on only the likely table/result panel removes MRI images,
        # charts and other GUI noise. To keep runtime bounded we only retry the
        # structurally best full-image variant (plus original when different).
        height, width = image.shape[:2]
        panel_box = _panel_crop_from_regions(best_regions, width, height) if bool(self.table_settings.get("auto_panel_crop", True)) else None
        if panel_box is not None:
            panel_image = image[panel_box.y1:panel_box.y2, panel_box.x1:panel_box.x2]
            panel_variants = [best_variant]
            if best_variant != "original":
                panel_variants.append("original")
            for variant in panel_variants:
                prepared = _preprocess_table_image(panel_image, variant)
                local_regions = self._detect_once(prepared, source_id=source_id, fallback_tokens=())
                regions = _translate_table_regions(local_regions, panel_box.x1, panel_box.y1)
                metrics = score_table_structure(regions)
                runs.append({"variant": variant, "scope": "panel", **metrics})
                numeric_score = float(metrics.get("score") or 0.0)
                if numeric_score > best_score:
                    best_regions = regions
                    best_score = numeric_score
                    best_variant = variant
                    best_scope = "panel"
        panel_suggestions = _panel_suggestions_from_variant_results(full_results, width, height)
        return best_regions, {
            "enabled": True,
            "selected_variant": best_variant,
            "selected_scope": best_scope,
            "selected_score": round(max(0.0, best_score), 2),
            "panel_crop": panel_box.to_list() if panel_box is not None else None,
            "panel_suggestions": panel_suggestions,
            "runs": runs,
            "selection_rule": "row regularity + column alignment + usable cell density - overlap penalty",
        }

    def detect_panels_with_benchmark(
        self,
        image: np.ndarray,
        *,
        source_id: str,
        panels: Sequence[dict[str, Any]],
    ) -> tuple[list[TableRegion], dict[str, Any]]:
        """Benchmark preprocessing independently inside user-defined table panels.

        Manual panel geometry is authoritative: no automatic crop is allowed to
        discard a second table. Each panel chooses its own best preprocessing
        variant and all selected table/cell geometry is translated back to the
        full source image.
        """
        variants = self.table_settings.get("preprocessing_variants") or [
            "original", "grayscale", "clahe", "invert_clahe", "adaptive"
        ]
        allowed = {"original", "grayscale", "clahe", "invert_clahe", "adaptive"}
        variants = [str(item) for item in variants if str(item) in allowed]
        if "original" not in variants:
            variants.insert(0, "original")

        all_regions: list[TableRegion] = []
        panel_results: list[dict[str, Any]] = []
        all_runs: list[dict[str, Any]] = []
        height, width = image.shape[:2]
        for panel_index, panel in enumerate(panels):
            box = panel.get("box")
            if not isinstance(box, Box):
                continue
            box = box.clamp(width, height)
            if box.width < 20 or box.height < 20:
                continue
            panel_id = str(panel.get("panel_id") or f"panel-{panel_index + 1}")
            panel_name = str(panel.get("name") or f"Panel {panel_index + 1}")
            crop = image[box.y1:box.y2, box.x1:box.x2]
            best_regions: list[TableRegion] = []
            best_score = -1.0
            best_variant = "original"
            panel_runs: list[dict[str, Any]] = []
            for variant in variants:
                prepared = _preprocess_table_image(crop, variant)
                local_source_id = f"{source_id}:{panel_id}"
                local_regions = self._detect_once(prepared, source_id=local_source_id, fallback_tokens=())
                translated = _translate_table_regions(local_regions, box.x1, box.y1)
                metrics = score_table_structure(translated)
                run = {
                    "panel_id": panel_id, "panel_name": panel_name,
                    "variant": variant, "scope": "manual_panel",
                    "panel_box": box.to_list(), **metrics,
                }
                panel_runs.append(run); all_runs.append(run)
                numeric_score = float(metrics.get("score") or 0.0)
                if numeric_score > best_score:
                    best_regions = translated
                    best_score = numeric_score
                    best_variant = variant
            all_regions.extend(best_regions)
            panel_results.append({
                "panel_id": panel_id, "panel_name": panel_name, "panel_box": box.to_list(),
                "selected_variant": best_variant,
                "selected_score": round(max(0.0, best_score), 2),
                "table_count": len(best_regions),
                "cell_count": sum(len(region.cells) for region in best_regions),
                "runs": panel_runs,
            })
        selected_score = (
            sum(float(item["selected_score"]) for item in panel_results) / len(panel_results)
            if panel_results else 0.0
        )
        return all_regions, {
            "enabled": True,
            "panel_mode": "manual",
            "selected_scope": "manual_panels",
            "selected_variant": "per-panel",
            "selected_score": round(selected_score, 2),
            "panel_count": len(panel_results),
            "panels": panel_results,
            "runs": all_runs,
            "selection_rule": "best preprocessing variant per user-defined panel",
        }

    def detect(self, image: np.ndarray, *, source_id: str, fallback_tokens: Sequence[OCRToken] = ()) -> list[TableRegion]:
        if bool(self.table_settings.get("preprocessing_benchmark", False)):
            regions, _ = self.detect_with_benchmark(image, source_id=source_id, fallback_tokens=fallback_tokens)
            return regions
        return self._detect_once(image, source_id=source_id, fallback_tokens=fallback_tokens)

    def smoke_test(self, image: np.ndarray) -> dict[str, Any]:
        regions = self.detect(image, source_id="model-smoke-test")
        return {"table_count": len(regions), "cell_count": sum(len(table.cells) for table in regions)}

    def info(self) -> dict[str, Any]:
        return {
            "provider": "paddleocr",
            "pipeline": "PP-StructureV3",
            "package_version": self._version,
            "engine_version": TABLE_ENGINE_VERSION,
            "device": self.settings.get("device", "cpu"),
            "inference_engine": self.settings.get("inference_engine", "paddle_static"),
            "cell_geometry_required": True,
        }
