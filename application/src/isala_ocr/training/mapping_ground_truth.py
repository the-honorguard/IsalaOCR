from __future__ import annotations

import hashlib
import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Sequence

from ..geometry import intersection_area as _intersection_area
from ..geometry import union as _union
from ..models import Box, OCRToken
from ..ocr.table_structure import TableCell, TableRegion
from .generic_detection import GenericBlock
from .table_cell_ground_truth import list_ground_truth_cells
from .table_panels import load_panel_profile, panel_boxes_for_image

LOGGER = logging.getLogger(__name__)
CANONICAL_MAPPING_GEOMETRY_VERSION = "canonical-table-cell-gt-v1"


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    ignored_suffixes = {".ini", ".yaml", ".yml", ".json", ".txt", ".log"}
    return sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
        and not any(part.startswith(".") for part in item.relative_to(path).parts)
        and item.suffix.lower() not in ignored_suffixes
    )


def _center(box: Box) -> tuple[float, float]:
    return ((box.x1 + box.x2) / 2.0, (box.y1 + box.y2) / 2.0)


def _assign_tokens_to_boxes(tokens: Sequence[OCRToken], boxes: Sequence[Box]) -> dict[int, list[OCRToken]]:
    """Assign an OCR token to at most one canonical GT cell."""
    assigned: dict[int, list[OCRToken]] = {index: [] for index in range(len(boxes))}
    for token in tokens:
        if token.box is None or not str(token.text or "").strip():
            continue
        token_area = max(1, token.box.width * token.box.height)
        center_x, center_y = _center(token.box)
        best_index: int | None = None
        best_score = 0.0
        for index, cell_box in enumerate(boxes):
            intersection = _intersection_area(token.box, cell_box)
            coverage = intersection / token_area
            center_inside = cell_box.x1 - 2 <= center_x <= cell_box.x2 + 2 and cell_box.y1 - 2 <= center_y <= cell_box.y2 + 2
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


def _cluster_rows(boxes: Sequence[Box]) -> list[list[int]]:
    if not boxes:
        return []
    heights = sorted(max(1, box.height) for box in boxes)
    median_height = heights[len(heights) // 2]
    tolerance = max(4.0, median_height * 0.55)
    indices = sorted(range(len(boxes)), key=lambda index: (_center(boxes[index])[1], boxes[index].x1))
    rows: list[list[int]] = []
    centers: list[float] = []
    for index in indices:
        center_y = _center(boxes[index])[1]
        selected: int | None = None
        best_distance = float("inf")
        for row_index, row_center in enumerate(centers):
            distance = abs(center_y - row_center)
            if distance <= tolerance and distance < best_distance:
                selected = row_index
                best_distance = distance
        if selected is None:
            rows.append([index])
            centers.append(center_y)
        else:
            rows[selected].append(index)
            centers[selected] = sum(_center(boxes[item])[1] for item in rows[selected]) / len(rows[selected])
    return [
        sorted(row, key=lambda index: boxes[index].x1)
        for _, row in sorted(zip(centers, rows), key=lambda item: item[0])
    ]


def canonical_table_regions(
    workspace: str | Path,
    source_id: str,
    tokens: Sequence[OCRToken],
    *,
    image_width: int,
    image_height: int,
) -> list[TableRegion]:
    """Reconstruct mapping table regions from canonical GT without model inference.

    Canonical GT owns the geometry after the table-first gate. Full-page OCR is
    used only to attach text to those already approved cells. No PP-Structure,
    RT-DETR or active table-cell model is initialized by this function.
    """
    raw_cells = list_ground_truth_cells(workspace, source_id)
    if not raw_cells:
        raise RuntimeError(f"Canonical table-cell GT has no cells for source {source_id}")

    # GT Studio review never records panel_id/panel_name on a cell (see
    # mapping_ground_truth_fast._configured_panel_regions()'s docstring), so
    # grouping by that field alone put every cell from every panel into one
    # "unassigned" bucket - one merged TableRegion (and table_id) spanning,
    # say, both the LV and RV tables. Row/column clustering then ran across
    # both panels' cells together, and any later per-table panel-context
    # match (there is only one table_id to match) could only ever pick one
    # side for every relation in the merged region. Partition by Table/Panel
    # Setup's own configured geometry first when it exists; a cell's own
    # panel_id remains the fallback for a project with no configured panels.
    configured_panels = panel_boxes_for_image(
        load_panel_profile(workspace), image_width, image_height
    )

    def _panel_id_for_cell(item: dict[str, Any]) -> str:
        if configured_panels:
            try:
                center_x = (int(item["x1"]) + int(item["x2"])) / 2
                center_y = (int(item["y1"]) + int(item["y2"])) / 2
            except (KeyError, TypeError, ValueError):
                pass
            else:
                for panel in configured_panels:
                    box = panel["box"]
                    if box.x1 <= center_x <= box.x2 and box.y1 <= center_y <= box.y2:
                        return str(panel["panel_id"])
        return str(item.get("panel_id") or "unassigned")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in raw_cells:
        panel_id = _panel_id_for_cell(item)
        grouped.setdefault(panel_id, []).append(item)

    regions: list[TableRegion] = []
    for panel_number, (panel_id, items) in enumerate(sorted(grouped.items()), start=1):
        boxes: list[Box] = []
        usable_items: list[dict[str, Any]] = []
        for item in items:
            try:
                box = Box(
                    int(item["x1"]), int(item["y1"]),
                    int(item["x2"]), int(item["y2"]),
                ).clamp(image_width, image_height)
            except (KeyError, TypeError, ValueError):
                continue
            if box.width <= 0 or box.height <= 0:
                continue
            boxes.append(box)
            usable_items.append(item)
        if not boxes:
            continue

        assigned = _assign_tokens_to_boxes(tokens, boxes)
        rows = _cluster_rows(boxes)
        row_and_column: dict[int, tuple[int, int]] = {}
        for row_index, row in enumerate(rows):
            for column_index, box_index in enumerate(row):
                row_and_column[box_index] = (row_index, column_index)

        table_box = _union(boxes)
        table_seed = f"{source_id}|{panel_id}|{table_box.to_list()}"
        table_id = "canonical-" + hashlib.sha256(table_seed.encode("utf-8")).hexdigest()[:24]
        cells: list[TableCell] = []
        for box_index, (item, box) in enumerate(zip(usable_items, boxes, strict=True)):
            row_index, column_index = row_and_column.get(box_index, (0, box_index))
            text, confidence = _weighted_text(assigned.get(box_index, ()))
            gt_id = str(item.get("gt_id") or "")
            if not gt_id:
                gt_id = "gt-" + hashlib.sha256(
                    f"{source_id}|{panel_id}|{box.to_list()}".encode("utf-8")
                ).hexdigest()[:24]
            cells.append(
                TableCell(
                    table_id=table_id,
                    cell_id=gt_id,
                    row_index=row_index,
                    column_index=column_index,
                    box=box,
                    text=text,
                    confidence=float(confidence),
                )
            )
        cells.sort(key=lambda cell: (cell.row_index, cell.column_index, cell.box.x1))
        regions.append(
            TableRegion(
                table_id=table_id,
                box=table_box,
                confidence=1.0,
                cells=tuple(cells),
                html="",
            )
        )
        LOGGER.debug(
            "Canonical GT panel %d source=%s panel=%s rows=%d cells=%d",
            panel_number, source_id, panel_id, len(rows), len(cells),
        )
    if not regions:
        raise RuntimeError(f"Canonical table-cell GT contains no usable cells for source {source_id}")
    return regions


def mark_canonical_geometry(blocks: Sequence[GenericBlock]) -> list[GenericBlock]:
    """Make provenance explicit after reusing the generic table integration code."""
    result: list[GenericBlock] = []
    for block in blocks:
        if block.block_type == "table_cell":
            result.append(replace(block, geometry_source="canonical_gt_cell"))
        elif block.block_type == "table":
            result.append(replace(block, geometry_source="canonical_gt_table"))
        else:
            result.append(block)
    return result
