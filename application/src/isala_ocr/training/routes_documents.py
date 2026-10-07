"""Read-only per-source document/output viewer routes, split out of
webui.create_web_app.

Same pattern as the other ``routes_*`` modules split out of ``webui.py``:
the handlers move here, but the helpers they call (``source_rows``,
``source_samples``, ``header_field_options``, ``source_study_info``,
the active project ``database`` proxy, ``workspace_root`` and
``safe_workspace_file``) stay in webui.py because other route groups
there also depend on them, and are passed in explicitly instead of
re-implemented.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, render_template

from ..models import Box
from ..ocr.table_structure import TableCell, normalize_table_column_layout, rasterize_table_columns
from .generic_detection import looks_like_value
from .json_store import read_json
from .mapping_ground_truth_fast import _configured_panel_regions
from .recognition_ground_truth import EXTRACTION_METHOD as CANONICAL_GT_CELL_EXTRACTION_METHOD
from .recognition_ground_truth import STALE_EXTRACTION_METHOD as CANONICAL_GT_CELL_STALE_EXTRACTION_METHOD
from .test_pipeline_sources import test_pipeline_source_ids


def _overlap_ratio(region: dict[str, int], panel: dict[str, object]) -> float:
    """Fraction of ``region`` covered by ``panel`` (0..1)."""
    px1, py1, px2, py2 = int(panel["x1"]), int(panel["y1"]), int(panel["x2"]), int(panel["y2"])
    ix1, iy1 = max(region["x1"], px1), max(region["y1"], py1)
    ix2, iy2 = min(region["x2"], px2), min(region["y2"], py2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area = max(1, (region["x2"] - region["x1"]) * (region["y2"] - region["y1"]))
    return inter / area


def _relation_side(context_text: str) -> str:
    """"left"/"right"/"unknown" straight from a relation's own OCR'd context
    text (its table/panel/column header), independent of any configured
    Table/Panel Setup geometry. Shared by ``_located_windows`` (labels V1/V2
    windows) and ``_identification_stage_data`` (labels individual boxes) so
    both agree on the same evidence.

    Matched with whitespace stripped from both the text and the vocabulary
    below (e.g. "right ventricle" is checked as "rightventricle"), because
    Pipeline B's OCR regularly glues adjacent words together with no space
    ("Leftventricle Volume Result") -- a plain substring check for "left
    ventricle" would silently miss that and fall through to "unknown", even
    though the text unambiguously says which side it is.
    """
    context_compact = "".join(context_text.casefold().split())
    if any(term in context_compact for term in ("rightventricle", "rechterventrikel", "rechts")):
        return "right"
    if any(term in context_compact for term in ("leftventricle", "linkerventrikel", "links")):
        return "left"
    return "unknown"


def _window_sides_from_relations(
    workspace_root: Path, source_id: str, windows: list[dict[str, Any]]
) -> dict[int, str]:
    """Best-guess left/right side per window (keyed by ``window_index``),
    read from Identificatie's own already-OCR'd relations. This is
    ``_located_windows``'s primary source of truth, ahead of the configured
    Table/Panel Setup geometry: Table/Panel Setup's boxes are drawn once
    against a single reference layout, so a document whose tables land
    somewhere else on the page (a different report layout, or one that has
    since drifted from that reference) has no overlap with any panel and
    ``_configured_panel_regions`` can never label it -- even though the
    table's own header text already says which side it is. Every relation
    inside a window casts one vote for that window's side (by simple
    majority) so a stray mismatched word elsewhere in the table does not
    flip the whole window. Returns {} (letting the caller fall back to
    geometry) whenever Identificatie hasn't run yet for this source, or no
    relation landed inside any window.
    """
    if not source_id or not windows:
        return {}
    path = workspace_root / "generic_detections" / f"{source_id}.json"
    if not path.is_file():
        return {}
    payload = read_json(path, {})
    blocks_by_id = {
        str(block.get("block_id") or ""): block
        for block in (payload.get("blocks") or [])
        if isinstance(block, dict)
    }
    votes: dict[int, Counter[str]] = {}
    for relation in payload.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        value_block = blocks_by_id.get(str(relation.get("value_block_id") or ""))
        if value_block is None:
            continue
        vx1, vy1 = int(value_block.get("x1") or 0), int(value_block.get("y1") or 0)
        vx2, vy2 = int(value_block.get("x2") or 0), int(value_block.get("y2") or 0)
        center_x, center_y = (vx1 + vx2) / 2, (vy1 + vy2) / 2
        window = next(
            (w for w in windows if w["x1"] <= center_x <= w["x2"] and w["y1"] <= center_y <= w["y2"]), None,
        )
        if window is None:
            continue
        side = _relation_side(str(relation.get("context_text") or ""))
        if side == "unknown":
            continue
        votes.setdefault(window["window_index"], Counter())[side] += 1
    return {window_index: counter.most_common(1)[0][0] for window_index, counter in votes.items() if counter}


def _back_link(
    workspace_root: Path, source_id: str, *, default_url: str, default_label: str
) -> tuple[str, str]:
    """Where a source's detail pages' "back" link should go.

    A proefpagina source must always lead back to the proefpagina itself
    directly, not through a training-review hop it has been deliberately
    filtered out of (see test_pipeline_sources.py) or even through this
    source's own Datablok page first -- every one of these detail pages
    (Tabellen, Cellen, Identificatie, and Datablok itself) shares this so a
    proefpagina visit never bounces through an extra page before reaching the
    proefpagina again. For a real training source, ``default_url``/
    ``default_label`` keep each page's own, already-correct hop (sub-pages go
    up to that source's Datablok view; Datablok itself goes to the full list).
    """
    if source_id in test_pipeline_source_ids(workspace_root):
        return f"/test-pipeline?source_id={source_id}", "← Proefpagina"
    return default_url, default_label


def _located_windows(
    workspace_root: Path, localization: dict[str, Any], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    """Every table region Pipeline A located, numbered top-to-bottom and labeled
    Links/Rechts (see ``output_review_tables``). Shared with the cell-detection
    view so both agree on the same windows.

    Labeled primarily from each window's own already-OCR'd relations (see
    ``_window_sides_from_relations``), falling back to the configured
    Table/Panel Setup geometry only when a window has no OCR evidence at all
    (for example before Identificatie/Pipeline B has run for this source).
    OCR content is preferred because it reflects the document actually in
    front of it; the configured panel geometry is a single fixed reference
    layout that silently goes stale the moment a document's table position
    differs from it (a different report layout, or one that has since
    drifted) -- exactly the case OCR content still gets right.
    """
    windows = [
        {
            "x1": int(item.get("x1") or 0), "y1": int(item.get("y1") or 0),
            "x2": int(item.get("x2") or 0), "y2": int(item.get("y2") or 0),
        }
        for item in (localization.get("tables") or [])
        if isinstance(item, dict)
    ]
    windows.sort(key=lambda region: region["y1"])
    for index, region in enumerate(windows, start=1):
        region["window_index"] = index
    panels = _configured_panel_regions(workspace_root, image_width, image_height)
    panel_name_by_side = {"left": "Links", "right": "Rechts"}
    for panel in panels:
        side = _relation_side(str(panel.get("panel_name") or "") + " " + str(panel.get("panel_id") or ""))
        if side != "unknown":
            panel_name_by_side[side] = str(panel["panel_name"])
    side_by_window = _window_sides_from_relations(
        workspace_root, str(localization.get("source_id") or ""), windows
    )
    for region in windows:
        side = side_by_window.get(region["window_index"])
        if side:
            region["table_label"] = panel_name_by_side.get(side, side)
            continue
        # No OCR evidence for this window (Identificatie hasn't run yet, or no
        # relation landed inside it) -- fall back to Table/Panel Setup's
        # configured geometry.
        best_panel = max(panels, key=lambda panel: _overlap_ratio(region, panel)) if panels else None
        region["table_label"] = (
            str(best_panel["panel_name"])
            if best_panel is not None and _overlap_ratio(region, best_panel) >= 0.50
            else "Onbekend"
        )
    # detect_with_benchmark() (table_structure.py) tries several preprocessing
    # variants (original/grayscale/clahe/invert_clahe/adaptive) per region and
    # keeps the best-scoring one; a low-contrast table can score wildly
    # differently between two otherwise-identical runs on the weaker variants
    # while the winning (usually contrast-boosted) variant stays stable -- see
    # test_pipeline_compare()'s docstring. Surfacing which variant actually
    # won, and its score, lets a compare view show *why* two runs of the same
    # model on the same pixels can still disagree, instead of just that they
    # do. Regions and windows are both already sorted top-to-bottom, so they
    # are matched by that shared ordering rather than by coordinates, which
    # differ slightly (a region is the pre-benchmark crop box, a window is the
    # final detected table boundary).
    benchmark_regions = sorted(
        (
            item for item in ((localization.get("preprocessing_benchmark") or {}).get("regions") or [])
            if isinstance(item, dict)
        ),
        key=lambda item: (item.get("region_box") or [0, 0])[1] if len(item.get("region_box") or []) > 1 else 0,
    )
    for region in windows:
        region["preprocessing_variant"] = None
        region["preprocessing_score"] = None
    for region, benchmark in zip(windows, benchmark_regions):
        region["preprocessing_variant"] = str(benchmark.get("selected_variant") or "") or None
        region["preprocessing_score"] = benchmark.get("selected_score")
    return windows


def _datablok_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Build ``output_review``'s view data for one source, or ``None`` if it hasn't run yet.

    Split out so the single-source ``/output-review/<source_id>`` route and the
    proefpagina's multi-stage compare view (``test_pipeline_compare``) build the
    exact same shape from the exact same data, instead of two implementations
    that could quietly drift apart.
    """
    path = safe_workspace_file(Path("extracted_output") / f"{source_id}.json")
    if not path.is_file():
        return None
    payload = read_json(path, {})
    measurements = []
    for field_key, value in (payload.get("measurements") or {}).items():
        if isinstance(value, dict):
            measurements.append({"field_key": field_key, **value})
    source = database.get_detection_source(source_id) or {}
    return {
        "source_id": source_id, "measurements": measurements,
        "generated_at": payload.get("generated_at") or "",
        "image_width": int(source.get("image_width") or 1),
        "image_height": int(source.get("image_height") or 1),
        "render_exists": (workspace_root / "source_renders" / f"{source_id}.png").is_file(),
        "identification_exists": (workspace_root / "generic_detections" / f"{source_id}.json").is_file(),
        "tables_exists": (workspace_root / "localization_detections" / f"{source_id}.json").is_file(),
        "cells_exists": (workspace_root / "localization_detections" / f"{source_id}.json").is_file(),
    }


def _measurement_diff_rows(
    new_datablok: dict[str, Any] | None, old_datablok: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Field-by-field diff between two ``_datablok_stage_data()`` results.

    Shared by the proefpagina compare screen (``test_pipeline_compare``) and
    the proefpagina list's per-row deviation alert (``test_pipeline``), so
    both use exactly the same "does this field differ" rule instead of two
    definitions that could quietly disagree. Returns ``[]`` when either side
    has no datablok yet -- nothing to compare.
    """
    if new_datablok is None or old_datablok is None:
        return []

    def _display_value(measurement: dict[str, Any]) -> str:
        value = measurement.get("parsed_value")
        if value is None:
            value = measurement.get("raw_text")
        if value is None or value == "":
            return ""
        unit = str(measurement.get("parsed_unit") or "")
        return f"{value} {unit}".strip()

    new_measurements = {str(item["field_key"]): item for item in new_datablok["measurements"]}
    old_measurements = {str(item["field_key"]): item for item in old_datablok["measurements"]}
    rows = []
    for field_key in sorted(set(new_measurements) | set(old_measurements)):
        left = new_measurements.get(field_key) or {}
        right = old_measurements.get(field_key) or {}
        rows.append({
            "field_key": field_key,
            "display_name": str(left.get("display_name") or right.get("display_name") or field_key),
            "left": _display_value(left) if left else "",
            "right": _display_value(right) if right else "",
            "differs": _display_value(left) != _display_value(right),
        })
    return rows


def _readout_diff_rows(
    new_readout: dict[str, Any] | None, old_readout: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Pair up the two sides' raw Recognition read-out samples by field, like
    ``_measurement_diff_rows`` does for the final datablok.

    ``_recognition_readout_stage_data`` sorts each side's samples
    independently by label, so the same field can land on different row
    indexes left and right whenever one side is missing a field the other
    has. Keying by field (falling back to the label when a sample has no
    ``field_key``, e.g. legacy data) and unioning both sides' keys puts the
    same field on the same row, with an empty cell on whichever side lacks it.
    """
    def _by_key(readout: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
        if not readout:
            return {}
        return {str(item["field_key"] or item["field_label"]): item for item in readout["samples"]}

    new_samples, old_samples = _by_key(new_readout), _by_key(old_readout)
    rows = []
    for key in sorted(set(new_samples) | set(old_samples), key=lambda k: (new_samples.get(k) or old_samples.get(k))["field_label"]):
        left, right = new_samples.get(key), old_samples.get(key)
        rows.append({
            "field_label": (left or right)["field_label"],
            "left_text": left["raw_ocr"] if left else "",
            "left_confidence": left["raw_confidence"] if left else None,
            "right_text": right["raw_ocr"] if right else "",
            "right_confidence": right["raw_confidence"] if right else None,
            "differs": (left["raw_ocr"] if left else "") != (right["raw_ocr"] if right else ""),
        })
    return rows


def _tables_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Build ``output_review_tables``'s view data, or ``None`` before Pipeline A has run.

    See ``_datablok_stage_data``'s docstring for why this is split out.
    """
    localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
    if not localization_path.is_file():
        return None
    localization = read_json(localization_path, {})
    source = database.get_detection_source(source_id) or {}
    image_width = int(localization.get("image_width") or source.get("image_width") or 1)
    image_height = int(localization.get("image_height") or source.get("image_height") or 1)
    return {
        "source_id": source_id,
        "located_tables": _located_windows(workspace_root, localization, image_width, image_height),
        "image_width": image_width, "image_height": image_height,
        "render_exists": (workspace_root / "source_renders" / f"{source_id}.png").is_file(),
        "cells_exists": bool(localization.get("tables")),
    }


def _table_cells_from_payload(table: dict[str, Any]) -> list[TableCell]:
    """Read raw saved geometry and repair older column numbering in memory."""
    raw_cells = [
        TableCell(
            table_id=str(table.get("table_id") or ""), cell_id=str(cell.get("cell_id") or index),
            row_index=int(cell.get("row_index") or 0), column_index=int(cell.get("column_index") or 0),
            box=Box(
                int(cell.get("x1") or 0), int(cell.get("y1") or 0),
                int(cell.get("x2") or 0), int(cell.get("y2") or 0),
            ),
            text="", confidence=float(cell.get("confidence") or 0),
            column_span=int(cell.get("column_span") or 1),
        )
        for index, cell in enumerate(table.get("cells") or [])
        if isinstance(cell, dict)
    ]
    return normalize_table_column_layout(raw_cells)


def _cells_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Build ``output_review_cells``'s view data, or ``None`` before Pipeline A has run.

    See ``_datablok_stage_data``'s docstring for why this is split out.
    """
    localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
    if not localization_path.is_file():
        return None
    localization = read_json(localization_path, {})
    source = database.get_detection_source(source_id) or {}
    image_width = int(localization.get("image_width") or source.get("image_width") or 1)
    image_height = int(localization.get("image_height") or source.get("image_height") or 1)
    windows = _located_windows(workspace_root, localization, image_width, image_height)

    mapping_path = safe_workspace_file(Path("generic_detections") / f"{source_id}.json")
    mapping_payload = read_json(mapping_path, {}) if mapping_path.is_file() else {}
    # "table_cell" blocks (generic_detection.py's integrate_table_regions())
    # are built directly from the same cell boxes this grid uses, so they are
    # preferred whenever present. "semantic" blocks carry page-wide OCR text
    # instead (used by fusion-strategy sources, including job 61's proefpagina
    # reruns, which force fusion for their own mapping pass -- see
    # routes_test_pipeline.py) and are a first fallback, checked per cell, so
    # a source with both never double-counts one cell's text from both
    # sources. A canonical-GT table-first source (built entirely through
    # Recognition GT Studio -- recognition_ground_truth.py) never runs
    # Pipeline B at all, so it has no generic_detections file whatsoever;
    # its per-cell text only exists as "canonical_gt_cell" samples, matched
    # here by the same ROI-containment technique as a last fallback.
    def _texts(block_type: str) -> list[dict[str, Any]]:
        return [
            block for block in (mapping_payload.get("blocks") or [])
            if isinstance(block, dict) and block.get("block_type") == block_type
            and str(block.get("text") or "").strip()
        ]

    table_cell_blocks = _texts("table_cell")
    semantic_blocks = _texts("semantic")
    gt_cell_samples = [
        {
            "text": str(sample.get("raw_ocr") or ""),
            "x1": int(sample.get("roi_x1") or 0), "y1": int(sample.get("roi_y1") or 0),
            "x2": int(sample.get("roi_x2") or 0), "y2": int(sample.get("roi_y2") or 0),
        }
        for sample in database.samples_for_source(source_id)
        if str(sample.get("extraction_method") or "") == CANONICAL_GT_CELL_EXTRACTION_METHOD
        and str(sample.get("raw_ocr") or "").strip()
    ]

    def _matching_texts(blocks: list[dict[str, Any]], cx1: int, cy1: int, cx2: int, cy2: int) -> list[str]:
        return [
            block["text"].strip() for block in blocks
            if cx1 <= (block["x1"] + block["x2"]) / 2 <= cx2
            and cy1 <= (block["y1"] + block["y2"]) / 2 <= cy2
        ]

    located_tables = [item for item in (localization.get("tables") or []) if isinstance(item, dict)]
    for window in windows:
        table = next(
            (item for item in located_tables if item.get("x1") == window["x1"] and item.get("y1") == window["y1"]),
            {},
        )
        rows: dict[int, dict[int, dict[str, Any]]] = {}
        headers: list[dict[str, Any]] = []
        for cell in _table_cells_from_payload(table):
            cx1, cy1, cx2, cy2 = cell.box.x1, cell.box.y1, cell.box.x2, cell.box.y2
            texts = (
                _matching_texts(table_cell_blocks, cx1, cy1, cx2, cy2)
                or _matching_texts(semantic_blocks, cx1, cy1, cx2, cy2)
                or _matching_texts(gt_cell_samples, cx1, cy1, cx2, cy2)
            )
            display_cell = {
                "text": " ".join(texts),
                "confidence": cell.confidence,
                "x1": cx1, "y1": cy1, "x2": cx2, "y2": cy2,
            }
            if cell.column_index < 0:
                headers.append(display_cell)
            else:
                rows.setdefault(cell.row_index, {})[cell.column_index] = display_cell
        column_count = max((max(cols) for cols in rows.values()), default=-1) + 1
        grid = [
            [rows[row_index].get(col) for col in range(column_count)]
            for row_index in sorted(rows)
        ]
        window["grid"] = grid
        window["headers"] = headers
        window["cell_count"] = len(headers) + sum(len(row) for row in rows.values())
        window["has_text"] = bool(table_cell_blocks or semantic_blocks or gt_cell_samples)

    return {
        "source_id": source_id, "windows": windows,
        "image_width": image_width, "image_height": image_height,
        "render_exists": (workspace_root / "source_renders" / f"{source_id}.png").is_file(),
    }


def _rasterized_cells_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Build the proefpagina's "Rasterisering" view: each window's raw
    detected cells (``_cells_stage_data``'s "Celdetectie") reshaped to one
    shared column raster (``rasterize_table_columns()``), as plain box
    geometry for an image overlay. This stage is about the reshaped *shape*
    of the grid, not which text ended up in which cell -- that stays on
    "Celdetectie" and "Welke kolommen/rijen naar Recognition gaan", so this
    never needs OCR text at all.
    """
    localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
    if not localization_path.is_file():
        return None
    localization = read_json(localization_path, {})
    source = database.get_detection_source(source_id) or {}
    image_width = int(localization.get("image_width") or source.get("image_width") or 1)
    image_height = int(localization.get("image_height") or source.get("image_height") or 1)
    windows = _located_windows(workspace_root, localization, image_width, image_height)

    located_tables = [item for item in (localization.get("tables") or []) if isinstance(item, dict)]
    for window in windows:
        table = next(
            (item for item in located_tables if item.get("x1") == window["x1"] and item.get("y1") == window["y1"]),
            {},
        )
        window["boxes"] = [
            {"x1": cell.box.x1, "y1": cell.box.y1, "x2": cell.box.x2, "y2": cell.box.y2}
            for cell in rasterize_table_columns(_table_cells_from_payload(table))
        ]

    return {
        "source_id": source_id, "windows": windows,
        "image_width": image_width, "image_height": image_height,
        "render_exists": (workspace_root / "source_renders" / f"{source_id}.png").is_file(),
    }


def _mapping_scope_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Which rasterized cells (``_cells_stage_data``) this run's mapping actually reads.

    Not a re-derivation of any detector-internal geometry: a cell counts as
    "included" purely by cross-referencing its box against this run's own
    materialized samples (``database.samples_for_source``, populated by
    ``materialize_confirmed_mappings`` during the run) by center-point
    containment -- the same technique ``_cells_stage_data`` already uses to
    attach OCR text to a cell. Cells with no matching sample were detected and
    rasterized but never picked up by a confirmed mapping.
    """
    data = _cells_stage_data(
        source_id, workspace_root=workspace_root, safe_workspace_file=safe_workspace_file, database=database
    )
    if data is None:
        return None
    mapped_boxes = [
        (
            float(sample.get("roi_x1") or 0), float(sample.get("roi_y1") or 0),
            float(sample.get("roi_x2") or 0), float(sample.get("roi_y2") or 0),
            str(sample.get("field_label") or sample.get("field_key") or ""),
        )
        for sample in database.samples_for_source(source_id)
    ]
    for window in data["windows"]:
        for row in window["grid"]:
            for cell in row:
                if not cell:
                    continue
                center_x, center_y = (cell["x1"] + cell["x2"]) / 2, (cell["y1"] + cell["y2"]) / 2
                match = next(
                    (label for x1, y1, x2, y2, label in mapped_boxes if x1 <= center_x <= x2 and y1 <= center_y <= y2),
                    None,
                )
                cell["included"] = match is not None
                cell["field_label"] = match or ""
    return data


def _recognition_readout_stage_data(source_id: str, *, database: Any) -> dict[str, Any] | None:
    """Raw per-field Recognition read-out for this run, before mapping into the final datablok.

    Straight from ``samples`` (``database.samples_for_source``) -- the same
    ``raw_ocr``/``raw_confidence`` the active Recognition model produced
    during this run, keyed by canonical field rather than by cell, since a
    cell's grid position is already shown in ``_mapping_scope_stage_data``.

    Excludes ``canonical_gt_cell``/``canonical_gt_cell_stale`` samples: those
    are Recognition GT Studio's own per-cell training crops
    (``recognition_ground_truth.py``, field_label defaulting to the generic
    "Tabelcel"), stored under the same source_id but unrelated to this run's
    actual field readout. A training-pipeline source that has also been used
    to build Recognition GT training data would otherwise dump dozens of
    unlabelled "Tabelcel" rows into this comparison, drowning out the real
    field-by-field comparison the compare screen's STAP 6 is meant to show.
    """
    samples = [
        sample for sample in database.samples_for_source(source_id)
        if str(sample.get("extraction_method") or "")
        not in {CANONICAL_GT_CELL_EXTRACTION_METHOD, CANONICAL_GT_CELL_STALE_EXTRACTION_METHOD}
    ]
    if not samples:
        return None
    rows = sorted(
        (
            {
                "field_key": str(sample.get("field_key") or ""),
                "field_label": str(sample.get("field_label") or sample.get("field_key") or ""),
                "raw_ocr": str(sample.get("raw_ocr") or ""),
                "raw_confidence": float(sample.get("raw_confidence") or 0),
            }
            for sample in samples
        ),
        key=lambda item: item["field_label"],
    )
    return {"source_id": source_id, "samples": rows}


def _table_context_anchors(payload: dict[str, Any], windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where each window's own identification text (``_relation_side``'s
    input) was actually OCR'd from on the image.

    A window's "Onbekend"/"Links"/"Rechts" label is decided purely from a
    text string (``context_text``, e.g. "Leftventricle Volume Result") --
    showing that string alone proves nothing about whether it was really
    read from a sensible place on the page. This reconstructs the actual
    OCR box that text came from:

    - For a PP-Structure table (``integrate_table_regions()``), that text is
      ``table_context = " | ".join(table_context_parts[:3])``, built from any
      row 0-2 that has no value-looking cell. This regroups that table's own
      ``table_cell`` blocks by row and rebuilds the same eligible rows, so
      the anchor box is the *exact* header row(s) the text came from, not
      the table's own outer box (which would just repeat the window and
      show nothing new).
    - A table with cells but no such header row (every row has a
      value-looking cell) falls back to the table's own ``table`` block --
      less precise, but still a real box instead of nothing.
    - A non-table ("semantic") relation's context comes from
      ``_header_context()``, itself a ``role == "header"`` block with its
      own box; matched back by exact text.

    Anchors are deduplicated by (window, box) and each carries its own
    resolved ``side`` (via ``_relation_side``), so a window whose text looks
    right but still shows "unknown" is visible as such right on its own
    anchor, not just in a detail table.
    """
    blocks = [block for block in (payload.get("blocks") or []) if isinstance(block, dict)]

    def _window_index(x1: float, y1: float, x2: float, y2: float) -> int | None:
        if not windows:
            return None
        center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
        window = next(
            (w for w in windows if w["x1"] <= center_x <= w["x2"] and w["y1"] <= center_y <= w["y2"]), None,
        )
        return window["window_index"] if window else None

    anchors: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def _add(window_index: int | None, text: str, x1: float, y1: float, x2: float, y2: float, precision: str) -> None:
        text = text.strip()
        if not text:
            return
        key = (window_index, round(x1), round(y1), round(x2), round(y2))
        if key in seen:
            return
        seen.add(key)
        anchors.append({
            "window_index": window_index, "text": text, "side": _relation_side(text),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2, "precision": precision,
        })

    cells_by_table: dict[str, dict[int, list[dict[str, Any]]]] = {}
    for block in blocks:
        if block.get("block_type") != "table_cell":
            continue
        table_id = str(block.get("table_id") or "")
        row_index = int(block.get("row_index") or 0)
        cells_by_table.setdefault(table_id, {}).setdefault(row_index, []).append(block)

    tables_with_header_anchor: set[str] = set()
    for table_id, rows in cells_by_table.items():
        for row_index in sorted(index for index in rows if index <= 2):
            row_cells = sorted(rows[row_index], key=lambda item: int(item.get("column_index") or 0))
            texts = [str(cell.get("text") or "").strip() for cell in row_cells]
            if not any(texts) or any(looks_like_value(text) for text in texts):
                continue
            row_text = " ".join(text for text in texts if text)
            x1 = min(float(cell.get("x1") or 0) for cell in row_cells)
            y1 = min(float(cell.get("y1") or 0) for cell in row_cells)
            x2 = max(float(cell.get("x2") or 0) for cell in row_cells)
            y2 = max(float(cell.get("y2") or 0) for cell in row_cells)
            _add(_window_index(x1, y1, x2, y2), row_text, x1, y1, x2, y2, "header_row")
            tables_with_header_anchor.add(table_id)

    for block in blocks:
        if block.get("block_type") != "table":
            continue
        table_id = str(block.get("table_id") or "")
        if table_id in tables_with_header_anchor:
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        x1, y1 = float(block.get("x1") or 0), float(block.get("y1") or 0)
        x2, y2 = float(block.get("x2") or 0), float(block.get("y2") or 0)
        _add(_window_index(x1, y1, x2, y2), text, x1, y1, x2, y2, "table_region")

    blocks_by_id = {str(block.get("block_id") or ""): block for block in blocks}
    header_blocks_by_text = {
        str(block.get("text") or "").strip().casefold(): block
        for block in blocks if block.get("block_type") == "semantic" and block.get("role") == "header"
    }
    for relation in payload.get("relations") or []:
        if not isinstance(relation, dict) or str(relation.get("table_id") or ""):
            continue  # table_cell relations are already covered above
        context_text = str(relation.get("context_text") or "").strip()
        header_block = header_blocks_by_text.get(context_text.casefold())
        if header_block is None:
            continue
        value_block = blocks_by_id.get(str(relation.get("value_block_id") or ""))
        if value_block is None:
            continue
        vx1, vy1 = float(value_block.get("x1") or 0), float(value_block.get("y1") or 0)
        vx2, vy2 = float(value_block.get("x2") or 0), float(value_block.get("y2") or 0)
        x1, y1 = float(header_block.get("x1") or 0), float(header_block.get("y1") or 0)
        x2, y2 = float(header_block.get("x2") or 0), float(header_block.get("y2") or 0)
        _add(_window_index(vx1, vy1, vx2, vy2), context_text, x1, y1, x2, y2, "header_line")

    return anchors


def _identification_stage_data(
    source_id: str, *, workspace_root: Path, safe_workspace_file: Callable[[str | Path], Path], database: Any,
) -> dict[str, Any] | None:
    """Build ``output_review_identification``'s view data, or ``None`` before Pipeline B has run.

    Each box carries its ``window_index`` (the located table window its value
    block's center point falls into, or ``None`` when no Pipeline A windows
    exist yet) alongside the returned ``windows`` list, so a caller can group
    boxes per window and show exactly what OCR text (if any) landed inside
    each one -- e.g. the proefpagina compare screen's STAP 2.5, which answers
    "did OCR miss this window entirely, misread its header text, or read it
    correctly but still fail to classify a side" instead of only showing a
    box.

    See ``_datablok_stage_data``'s docstring for why this is split out.
    """
    localization_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
    localization = read_json(localization_path, {}) if localization_path.is_file() else {}
    source = database.get_detection_source(source_id) or {}
    image_width = int(localization.get("image_width") or source.get("image_width") or 1)
    image_height = int(localization.get("image_height") or source.get("image_height") or 1)
    windows = _located_windows(workspace_root, localization, image_width, image_height) if localization else []

    path = safe_workspace_file(Path("generic_detections") / f"{source_id}.json")
    if not path.is_file():
        return None
    payload = read_json(path, {})
    blocks_by_id = {
        str(block.get("block_id") or ""): block
        for block in (payload.get("blocks") or [])
        if isinstance(block, dict)
    }
    boxes = []
    for relation in payload.get("relations") or []:
        if not isinstance(relation, dict):
            continue
        value_block = blocks_by_id.get(str(relation.get("value_block_id") or ""))
        if value_block is None:
            continue
        vx1, vy1 = int(value_block.get("x1") or 0), int(value_block.get("y1") or 0)
        vx2, vy2 = int(value_block.get("x2") or 0), int(value_block.get("y2") or 0)
        center_x, center_y = (vx1 + vx2) / 2, (vy1 + vy2) / 2
        window = next(
            (w for w in windows if w["x1"] <= center_x <= w["x2"] and w["y1"] <= center_y <= w["y2"]), None,
        )
        if windows and window is None:
            continue
        label_block = blocks_by_id.get(str(relation.get("label_block_id") or ""))
        context_text = str(relation.get("context_text") or "")
        side = _relation_side(context_text)
        boxes.append({
            "x1": vx1, "y1": vy1, "x2": vx2, "y2": vy2,
            "window_index": window["window_index"] if window else None,
            "label_text": str((label_block or {}).get("text") or ""),
            "value_text": str(value_block.get("text") or ""),
            "context_text": context_text,
            "has_table_id": bool(relation.get("table_id") or ""),
            "side": side,
        })
    return {
        "source_id": source_id, "boxes": boxes, "windows": windows,
        "context_anchors": _table_context_anchors(payload, windows),
        "image_width": image_width, "image_height": image_height,
        "render_exists": (workspace_root / "source_renders" / f"{source_id}.png").is_file(),
    }


def register_document_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    source_rows: Callable[[], list[dict[str, Any]]],
    source_samples: Callable[[str], list[dict[str, Any]]],
    header_field_options: Callable[[], list[dict[str, Any]]],
    source_study_info: Callable[[str], tuple[dict[str, Any] | None, list[dict[str, Any]]]],
    locator_label_threshold: float,
) -> None:
    @app.get("/documents")
    def documents():
        return render_template("documents.html", sources=source_rows())

    @app.get("/documents/<source_id>")
    def document(source_id: str):
        samples = source_samples(source_id)
        if not samples:
            abort(404)
        field_options = {item["field_key"]: item for item in header_field_options()}
        fallback_count = 0
        # One directory scan instead of one safe_workspace_file(...).is_file()
        # (a full symlink-resolving realpath per call) per sample - the same
        # fix already applied to detection_review_source_rows(). A sample's
        # crop_path is always "crops/original/<source_id>/<field_key>.png"
        # (see collector.py), and every sample here is this one source_id, so
        # an in-memory set-membership check on that one directory's filenames
        # answers the same question.
        crop_dir = workspace_root() / "crops" / "original" / source_id
        existing_crop_names = {entry.name for entry in crop_dir.iterdir() if entry.is_file()} if crop_dir.is_dir() else set()
        for sample in samples:
            method = str(sample.get("extraction_method") or "")
            sample["is_fallback"] = method in {"fixed_fallback", "fixed_roi"}
            fallback_count += int(sample["is_fallback"])
            profile_field = field_options.get(str(sample.get("field_key") or ""), {})
            sample["canonical_header"] = str(profile_field.get("canonical_label") or sample.get("field_label") or "")
            sample["panel"] = str(profile_field.get("panel") or "")
            crop_path_value = str(sample.get("crop_path") or "")
            sample["crop_exists"] = bool(crop_path_value) and Path(crop_path_value).name in existing_crop_names
            sample["can_train_header"] = bool(
                str(sample.get("locator_label_text") or "").strip()
                and str(sample.get("header_crop_path") or "").strip()
            )
            if sample["is_fallback"]:
                matched = str(sample.get("locator_label_text") or "").strip()
                if matched:
                    sample["fallback_reason"] = (
                        f"Beste rijheadermatch '{matched}' bleef onder de acceptatiedrempel "
                        f"van {locator_label_threshold * 100:.0f}%."
                    )
                else:
                    sample["fallback_reason"] = (
                        "Er is geen bruikbare rijheadertekst gevonden; daarom zijn de vaste profielcoördinaten gebruikt."
                    )
        study_info, study_info_fields = source_study_info(source_id)
        return render_template(
            "document.html", source_id=source_id, samples=samples,
            image_width=samples[0]["image_width"], image_height=samples[0]["image_height"],
            render_exists=(workspace_root() / "source_renders" / f"{source_id}.png").is_file(),
            study_info=study_info, study_info_fields=study_info_fields,
            extracted_output_exists=(workspace_root() / "extracted_output" / f"{source_id}.json").is_file(),
            fallback_count=fallback_count, locator_label_threshold=locator_label_threshold,
        )

    @app.get("/output-review/<source_id>")
    def output_review(source_id: str):
        data = _datablok_stage_data(
            source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file, database=database
        )
        if data is None:
            abort(404)
        back_url, back_label = _back_link(
            workspace_root(), source_id, default_url="/process/value-review", default_label="← Alle datablokken"
        )
        return render_template("output_review.html", back_url=back_url, back_label=back_label, **data)

    @app.get("/output-review/<source_id>/tabellen")
    def output_review_tables(source_id: str):
        """Show which tables were located, and which configured table name each got.

        Nothing else: no cell content, no row/column structure, no mapping
        outcome. Just window -> label, using the same mechanism as Table/Panel
        Setup (``table_panel_profile.json``, geometric overlap against the
        located regions) rather than the old, fragile per-relation text guess.
        """
        data = _tables_stage_data(
            source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file, database=database
        )
        if data is None:
            abort(404)
        back_url, back_label = _back_link(
            workspace_root(), source_id,
            default_url=f"/output-review/{source_id}", default_label="← Datablok",
        )
        return render_template("output_tables.html", back_url=back_url, back_label=back_label, **data)

    @app.get("/output-review/<source_id>/cellen")
    def output_review_cells(source_id: str):
        """Show the actual row/column grid per window, like GT Studio (Stap 7-9).

        The previous version of this page plotted Pipeline A's cell boxes flat
        across the whole page -- geometrically correct, but not what "cell
        detection" means in this project: GT Studio, Celdetector trainen and
        Tabelstudio all work from row/column grid structure, not a scattered
        box list. ``localization_detections`` already carries that same grid
        (each cell has ``row_index``/``column_index`` from the active, trained
        table-cell detector); this fills in each cell's text from the OCR
        blocks Pipeline B produced (by center-point containment) when that
        stage has run, and renders one real grid per window instead of one
        global scatter.
        """
        data = _cells_stage_data(
            source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file, database=database
        )
        if data is None:
            abort(404)
        back_url, back_label = _back_link(
            workspace_root(), source_id,
            default_url=f"/output-review/{source_id}/tabellen", default_label="← Tabelherkenning",
        )
        return render_template("output_cells.html", back_url=back_url, back_label=back_label, **data)

    @app.get("/output-review/<source_id>/identificatie")
    def output_review_identification(source_id: str):
        """Show every within-window box and the text used to identify its side.

        Debugging aid for the deployment ("fusion") mapping path: the boxes a
        source's confirmed measurements came from are only a fraction of what
        was actually detected. This renders every candidate relation's value
        box plus the label text and context text used to decide which table
        (and therefore which canonical field) it belongs to, so a rejected
        candidate's cause is visible directly on the image instead of only in
        the raw JSON.

        Scoped to relations that actually fall inside a located table window
        (Pipeline A's regions): the page-wide generic OCR pass also treats
        scan parameters, patient info and DICOM-viewer chrome (Flip Angle,
        Scan Nr, HR, BSA, ...) as label/value "relations", since it has no
        notion of "this is a table" -- those were never eligible for mapping
        anyway (see mapping.py's own geometry gate), so showing them here
        just buries the ones that matter.
        """
        data = _identification_stage_data(
            source_id, workspace_root=workspace_root(), safe_workspace_file=safe_workspace_file, database=database
        )
        if data is None:
            abort(404)
        back_url, back_label = _back_link(
            workspace_root(), source_id, default_url=f"/output-review/{source_id}", default_label="← Datablok",
        )
        return render_template("output_identification.html", back_url=back_url, back_label=back_label, **data)
