from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .db import TrainingDatabase
from .generic_detection import normalize_text
from .projects import resolve_project_workspace
from .table_cell_ground_truth import list_ground_truth_cells, list_ground_truth_sources

EXTRACTION_METHOD = "canonical_gt_cell"
STALE_EXTRACTION_METHOD = "canonical_gt_cell_stale"
PROFILE = "recognition_ground_truth"
SCOPE_FILENAME = "recognition_scope.json"
TABLE_STUDIO_FILENAME = "table_studio_roles.json"


def table_studio_roles(workspace: str | Path) -> dict[str, dict[str, str]]:
    """Load semantic column roles without modifying canonical cell geometry."""
    root = resolve_project_workspace(workspace)
    path = root / TABLE_STUDIO_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for table_id, item in tables.items():
        if not isinstance(item, dict):
            continue
        roles = item.get("columns") if isinstance(item.get("columns"), dict) else item
        result[str(table_id)] = {
            str(column): str(role)
            for column, role in roles.items()
            if str(column).lstrip("-").isdigit()
            and str(role) in {"label", "value", "unit", "header", "skip"}
        }
    return result


def relation_panel_id(relation: dict[str, Any], panel_by_id: dict[str, dict[str, Any]]) -> str:
    """Resolve which Table/Panel Setup panel a detected relation belongs to.

    A relation's own ``table_id`` is a per-source, per-detection-run
    identifier (hashed from canonical GT geometry) - it never matches the
    identifiers Table/Panel Setup or Table Studio use, which are project-wide
    ``panel_id`` values. The only bridge between the two is ``context_text``,
    which ``_enrich_relations_with_panel_context()`` stamps with the panel's
    name and/or id at detection time. Shared by both Mapping Studio routes
    (``routes_mapping_studio.py`` and ``routes_roi_mapping_studio.py``) so a
    column role such as "Overslaan" (skip), set once in Table Studio, hides
    that column's relations consistently in either one.
    """
    parts = [part.strip() for part in str(relation.get("context_text") or "").split("|")]
    # Panel context is persisted as human-readable name plus optional id.
    # Older mapping runs only persisted the name, so do not assume the id is
    # always the second token.
    normalized_parts = {normalize_text(part) for part in parts if part}
    for panel_id, panel in panel_by_id.items():
        panel_name = normalize_text(str(panel.get("name") or ""))
        if normalize_text(panel_id) in normalized_parts or (
            panel_name and panel_name in normalized_parts
        ):
            return panel_id
    return ""


def table_studio_rows(workspace: str | Path) -> dict[str, list[int]]:
    root = resolve_project_workspace(workspace)
    path = root / TABLE_STUDIO_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {}
    tables = payload.get("tables") if isinstance(payload, dict) else None
    if not isinstance(tables, dict):
        return {}
    return {
        str(table_id): sorted({int(row) for row in item.get("rows", []) if str(row).lstrip("-").isdigit()})
        for table_id, item in tables.items()
        if isinstance(item, dict) and isinstance(item.get("rows"), list)
    }


def save_table_studio_roles(
    workspace: str | Path,
    tables: dict[str, dict[str, str]],
    *,
    rows: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    payload = {
        "schema_version": 2,
        "tables": {
            str(table_id): {
                "columns": {
                    str(column): str(role)
                    for column, role in roles.items()
                    if str(column).lstrip("-").isdigit()
                    and str(role) in {"label", "value", "unit", "header", "skip"}
                },
                "rows": sorted({int(row) for row in ((rows or {}).get(str(table_id)) or [])}),
            }
            for table_id, roles in tables.items()
            if isinstance(roles, dict)
        },
    }
    (root / TABLE_STUDIO_FILENAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def recognition_scope(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    path = root / SCOPE_FILENAME
    if not path.is_file():
        return {"mode": "all", "tables": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return {"mode": "all", "tables": {}}
    if not isinstance(payload, dict) or payload.get("mode") != "selected":
        return {"mode": "all", "tables": {}}
    tables = payload.get("tables")
    if isinstance(tables, dict):
        return {"mode": "selected", "tables": {
            str(table): {
                "rows": sorted({int(row) for row in (item.get("rows") or []) if str(row).lstrip("-").isdigit()}),
                "columns": sorted({int(column) for column in (item.get("columns") or []) if str(column).lstrip("-").isdigit()}),
                **({"legacy_columns_only": True} if item.get("legacy_columns_only") else {}),
            }
            for table, item in tables.items() if isinstance(item, dict)
        }}
    # Read the previous panel/column format so existing projects remain usable.
    panels = payload.get("panels")
    if isinstance(panels, dict):
        return {"mode": "selected", "tables": {
            str(panel): {"rows": [], "columns": sorted({int(column) for column in columns if str(column).lstrip("-").isdigit()}), "legacy_columns_only": True}
            for panel, columns in panels.items() if isinstance(columns, list)
        }}
    return {"mode": "all", "tables": {}}


def save_recognition_scope(workspace: str | Path, tables: dict[str, dict[str, list[int]]]) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    payload = {"schema_version": 2, "mode": "selected", "tables": {
        str(table): {
            "rows": sorted({int(row) for row in (selection.get("rows") or [])}),
            "columns": sorted({int(column) for column in (selection.get("columns") or [])}),
        }
        for table, selection in tables.items()
        if isinstance(selection, dict)
    }}
    (root / SCOPE_FILENAME).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _cell_table_id(cell: dict[str, Any], panels: list[dict[str, Any]] | None = None) -> str:
    explicit = str(cell.get("table_id") or cell.get("panel_id") or cell.get("panel_name") or "").strip()
    if explicit:
        return explicit
    if panels:
        center_x = (int(cell.get("x1") or 0) + int(cell.get("x2") or 0)) / 2
        center_y = (int(cell.get("y1") or 0) + int(cell.get("y2") or 0)) / 2
        for panel in panels:
            width = float(panel.get("reference_width") or 0)
            height = float(panel.get("reference_height") or 0)
            if width <= 0 or height <= 0:
                continue
            x1, y1 = float(panel.get("x1") or 0) * width, float(panel.get("y1") or 0) * height
            x2, y2 = float(panel.get("x2") or 0) * width, float(panel.get("y2") or 0) * height
            if x1 <= center_x <= x2 and y1 <= center_y <= y2:
                return str(panel.get("panel_id") or panel.get("name") or "__default__")
    return "__default__"


def _profile_panels(workspace: str | Path) -> list[dict[str, Any]]:
    root = resolve_project_workspace(workspace)
    path = root / "table_panel_profile.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, TypeError):
        return []
    panels = payload.get("panels") if isinstance(payload, dict) else None
    if not isinstance(panels, list):
        return []
    reference_width = (payload.get("reference_width") if isinstance(payload, dict) else 0) or 0
    reference_height = (payload.get("reference_height") if isinstance(payload, dict) else 0) or 0
    return [{**panel, "reference_width": reference_width, "reference_height": reference_height} for panel in panels if isinstance(panel, dict)]


def _cluster_axis(cells: list[dict[str, Any]], axis: str) -> list[list[dict[str, Any]]]:
    if not cells:
        return []
    starts = [int(cell.get(axis + "1") or 0) for cell in cells]
    ends = [int(cell.get(axis + "2") or 0) for cell in cells]
    sizes = sorted(max(1, end - start) for start, end in zip(starts, ends))
    tolerance = max(8, int(sizes[len(sizes) // 2] * 0.45))
    groups: list[list[dict[str, Any]]] = []
    centers: list[float] = []
    for index in sorted(range(len(cells)), key=lambda item: (starts[item] + ends[item]) / 2):
        center = (starts[index] + ends[index]) / 2
        nearest = min(range(len(centers)), key=lambda item: abs(centers[item] - center), default=-1)
        if nearest < 0 or abs(centers[nearest] - center) > tolerance:
            groups.append([cells[index]])
            centers.append(center)
        else:
            groups[nearest].append(cells[index])
            centers[nearest] = sum((int(item.get(axis + "1") or 0) + int(item.get(axis + "2") or 0)) / 2 for item in groups[nearest]) / len(groups[nearest])
    return [group for _, group in sorted(zip(centers, groups), key=lambda item: item[0])]


def _indexed_cells(cells: list[dict[str, Any]], workspace: str | Path | None = None) -> list[dict[str, Any]]:
    """Build occupied row/column raster cells from detection-box center lines."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    panels = _profile_panels(workspace) if workspace is not None else []
    for cell in cells:
        grouped.setdefault(_cell_table_id(cell, panels), []).append(cell)
    result: list[dict[str, Any]] = []
    for table_id, table_cells in grouped.items():
        rows = _cluster_axis(table_cells, "y")
        columns = _cluster_axis(table_cells, "x")
        row_by_id = {id(cell): row for row, group in enumerate(rows) for cell in group}
        column_by_id = {id(cell): column for column, group in enumerate(columns) for cell in group}
        occupied: dict[tuple[int, int], list[dict[str, Any]]] = {}
        for cell in table_cells:
            occupied.setdefault((row_by_id[id(cell)], column_by_id[id(cell)]), []).append(cell)
        for (row_index, column_index), members in sorted(occupied.items()):
            x1 = round(sum(int(item.get("x1") or 0) for item in columns[column_index]) / len(columns[column_index]))
            x2 = round(sum(int(item.get("x2") or 0) for item in columns[column_index]) / len(columns[column_index]))
            y1 = round(sum(int(item.get("y1") or 0) for item in rows[row_index]) / len(rows[row_index]))
            y2 = round(sum(int(item.get("y2") or 0) for item in rows[row_index]) / len(rows[row_index]))
            member_ids = ",".join(sorted(str(item.get("gt_id") or item.get("cell_id") or "") for item in members))
            raster_id = "gt-" + hashlib.sha256(f"{table_id}|{row_index}|{column_index}|{x1},{y1},{x2},{y2}|{member_ids}".encode()).hexdigest()[:24]
            result.append({**members[0], "gt_id": raster_id, "table_id": table_id, "row_index": row_index, "column_index": column_index, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "provenance": "occupied_detection_raster"})
    return result


def recognition_scope_options(workspace: str | Path) -> list[dict[str, Any]]:
    root = resolve_project_workspace(workspace)
    options: dict[str, dict[str, Any]] = {}
    for source in list_ground_truth_sources(root):
        source_id = str(source.get("source_id") or "")
        cells = _indexed_cells(list_ground_truth_cells(root, source_id), root)
        for cell in cells:
            table_id = _cell_table_id(cell)
            if not table_id or table_id == "__default__":
                continue
            scope_id = f"{source_id}::{table_id}"
            item = options.setdefault(scope_id, {"table_id": scope_id, "table_name": "", "source_id": source_id, "rows": set(), "columns": set()})
            item["rows"].add(int(cell.get("row_index", -1)))
            item["columns"].add(int(cell.get("column_index", -1)))
    return [{**item, "rows": sorted(item["rows"]), "columns": sorted(item["columns"])} for item in sorted(options.values(), key=lambda value: value["table_id"])]


def recognition_scope_preview(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    profile_panels = {str(panel.get("panel_id") or ""): panel for panel in _profile_panels(root)}
    all_tables: list[dict[str, Any]] = []
    first_source_id = ""
    for source in list_ground_truth_sources(root):
        source_id = str(source.get("source_id") or "")
        cells = _indexed_cells(list_ground_truth_cells(root, source_id), root)
        if cells and (root / "source_renders" / f"{source_id}.png").is_file():
            if not first_source_id:
                first_source_id = source_id
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cell in cells:
                table_id = _cell_table_id(cell)
                if table_id and table_id != "__default__":
                    grouped.setdefault(table_id, []).append(cell)
            tables = []
            for table_id, table_cells in sorted(grouped.items()):
                panel = profile_panels.get(table_id)
                if panel:
                    reference_width = float(panel.get("reference_width") or 0)
                    reference_height = float(panel.get("reference_height") or 0)
                else:
                    reference_width = max(int(item.get("x2") or 0) for item in table_cells)
                    reference_height = max(int(item.get("y2") or 0) for item in table_cells)
                # A profile panel is only a coarse table assignment hint. Its
                # bounds differ between report layouts, so preview the exact
                # table raster derived from this source's canonical GT cells.
                crop = {
                    "x1": max(0, min(int(item.get("x1") or 0) for item in table_cells) - 4),
                    "y1": max(0, min(int(item.get("y1") or 0) for item in table_cells) - 4),
                    "x2": max(int(item.get("x2") or 0) for item in table_cells) + 4,
                    "y2": max(int(item.get("y2") or 0) for item in table_cells) + 4,
                }
                def axis_regions(index_key: str) -> list[dict[str, int]]:
                    grouped: dict[int, list[dict[str, Any]]] = {}
                    for item in table_cells:
                        index = int(item.get(index_key) or 0)
                        grouped.setdefault(index, []).append(item)
                    return [{
                        "index": index,
                        "x1": min(int(item.get("x1") or 0) for item in items),
                        "y1": min(int(item.get("y1") or 0) for item in items),
                        "x2": max(int(item.get("x2") or 0) for item in items),
                        "y2": max(int(item.get("y2") or 0) for item in items),
                    } for index, items in sorted(grouped.items())]
                tables.append({
                    "table_id": f"{source_id}::{table_id}",
                    "source_id": source_id,
                    "table_name": "",
                    "cells": table_cells,
                    "render_width": round(reference_width),
                    "render_height": round(reference_height),
                    "rows": axis_regions("row_index"),
                    "columns": axis_regions("column_index"),
                    "crop": crop,
                })
            all_tables.extend(tables)
    return {"source_id": first_source_id, "cells": [], "tables": all_tables}


def _safe_id(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text or hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:20]


def _crop_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def recognition_gt_counts(database: TrainingDatabase) -> dict[str, int]:
    return database.samples_status_counts(EXTRACTION_METHOD)


def materialize_recognition_ground_truth(
    workspace: str | Path,
    *,
    recognition_engine: Any | None = None,
) -> dict[str, Any]:
    """Materialize neutral crop->text samples directly from canonical geometry GT.

    This is Model Factory input. It deliberately has no dependency on Mapping
    Studio, field definitions, aliases, units, application profiles or structured
    output. Every canonical table-cell GT box becomes a recognition sample.
    """
    import cv2

    root = resolve_project_workspace(workspace)
    database = TrainingDatabase(root / "samples.sqlite3")
    output_root = root / "recognition_ground_truth" / "crops"
    output_root.mkdir(parents=True, exist_ok=True)
    scope = recognition_scope(root)

    expected_ids: set[str] = set()
    created = 0
    updated = 0
    source_count = 0
    recognized = 0

    for source in list_ground_truth_sources(root):
        source_id = str(source.get("source_id") or "").strip()
        cells = _indexed_cells(list_ground_truth_cells(root, source_id), root)
        if scope["mode"] == "selected":
            selected = scope.get("tables") or {}
            def selection_for(cell: dict[str, Any]) -> dict[str, Any]:
                table_id = _cell_table_id(cell)
                return selected.get(f"{source_id}::{table_id}", selected.get(table_id, {}))
            cells = [
                cell for cell in cells
                if (
                    (selection_for(cell).get("legacy_columns_only") or int(cell.get("row_index", -1)) in set(selection_for(cell).get("rows") or []))
                    and int(cell.get("column_index", -1)) in set(selection_for(cell).get("columns") or [])
                )
            ]
        if not source_id or not cells:
            continue
        render_path = root / "source_renders" / f"{source_id}.png"
        image = cv2.imread(str(render_path), cv2.IMREAD_COLOR)
        if image is None:
            raise FileNotFoundError(f"Bronrender ontbreekt voor Recognition GT: {render_path}")
        height, width = image.shape[:2]
        prepared: list[tuple[dict[str, Any], Any, Path, str]] = []
        source_dir = output_root / _safe_id(source_id)
        source_dir.mkdir(parents=True, exist_ok=True)

        for cell in cells:
            gt_id = str(cell.get("gt_id") or "").strip()
            if not gt_id:
                continue
            x1 = max(0, min(width, int(cell.get("x1") or 0)))
            y1 = max(0, min(height, int(cell.get("y1") or 0)))
            x2 = max(0, min(width, int(cell.get("x2") or 0)))
            y2 = max(0, min(height, int(cell.get("y2") or 0)))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image[y1:y2, x1:x2].copy()
            crop_path = source_dir / f"{_safe_id(gt_id)}.png"
            if not cv2.imwrite(str(crop_path), crop):
                raise OSError(f"Kon Recognition-GT-crop niet schrijven: {crop_path}")
            sample_id = f"recgt-{_safe_id(gt_id)}"
            expected_ids.add(sample_id)
            prepared.append((cell, crop, crop_path, sample_id))

        recognized_rows: list[list[Any]] = [[] for _ in prepared]
        if recognition_engine is not None and prepared:
            recognition_engine.warmup()
            recognized_rows = recognition_engine.recognize_many([item[1] for item in prepared])
            recognized += len(prepared)

        for index, (cell, crop, crop_path, sample_id) in enumerate(prepared):
            tokens = recognized_rows[index] if index < len(recognized_rows) else []
            raw_text = " ".join(str(token.text) for token in tokens if str(token.text)).strip()
            confidence = min((float(token.confidence) for token in tokens), default=0.0)
            gt_id = str(cell.get("gt_id") or "")
            panel_name = str(cell.get("panel_name") or cell.get("panel_id") or "Tabelcel")
            relative_crop = crop_path.relative_to(root).as_posix()
            was_created = database.upsert_sample({
                "sample_id": sample_id,
                "source_id": source_id,
                "profile": PROFILE,
                "field_key": f"recognition.{_safe_id(gt_id)}",
                "field_label": panel_name,
                "crop_path": relative_crop,
                "raw_ocr": raw_text,
                "raw_confidence": confidence,
                "raw_variant": "baseline_recognition_gt" if recognition_engine is not None else "awaiting_baseline_recognition",
                "image_width": width,
                "image_height": height,
                "roi_x1": int(cell.get("x1") or 0),
                "roi_y1": int(cell.get("y1") or 0),
                "roi_x2": int(cell.get("x2") or 0),
                "roi_y2": int(cell.get("y2") or 0),
                "extraction_method": EXTRACTION_METHOD,
                "locator_confidence": 1.0,
                "locator_label_text": "",
                "locator_version": "canonical_table_cell_gt_v1",
                "crop_sha256": _crop_hash(crop_path),
            })
            # The geometry authority is the canonical table-cell GT itself. Keep
            # these samples OUT of the legacy Application value/ROI review, which
            # selects roi_review_status='correct'. Recognition review starts at
            # the literal crop->text label instead.
            database.review_roi(sample_id, "deferred", "Geometry authority: canonical table-cell Ground Truth")
            created += int(was_created)
            updated += int(not was_created)
        source_count += 1

    stale_ids = database.mark_stale_samples(EXTRACTION_METHOD, expected_ids, STALE_EXTRACTION_METHOD)

    return {
        "source_count": source_count,
        "sample_count": len(expected_ids),
        "created": created,
        "updated": updated,
        "recognized": recognized,
        "stale": len(stale_ids),
        "counts": recognition_gt_counts(database),
        "extraction_method": EXTRACTION_METHOD,
        "scope": scope,
    }
