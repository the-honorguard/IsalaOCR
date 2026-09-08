from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .projects import resolve_project_workspace


FILENAME = "table_region_ground_truth.json"


def _path(workspace: str | Path) -> Path:
    return resolve_project_workspace(workspace) / FILENAME


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError):
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_table_region_ground_truth(workspace: str | Path) -> dict[str, Any]:
    payload = _read(_path(workspace))
    sources = payload.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    return {
        "schema_version": 1,
        "type": "table_region_ground_truth",
        "sources": sources,
        "updated_at": str(payload.get("updated_at") or ""),
    }


def list_table_region_sources(workspace: str | Path) -> list[dict[str, Any]]:
    """Return the raw region-detector Ground Truth.

    This view is deliberately semantic-free. It is the authority used by the
    table-region dataset builder, where every annotation belongs to the single
    ``table_region`` class. Panel identity (left/right) is attached only by
    :func:`list_table_regions`, which is consumed by downstream cell workflows.
    """
    payload = load_table_region_ground_truth(workspace)
    result: list[dict[str, Any]] = []
    for source_id, source in sorted((payload.get("sources") or {}).items()):
        if not isinstance(source, dict):
            continue
        regions = [dict(item) for item in source.get("regions") or [] if isinstance(item, dict)]
        result.append({
            **source,
            "source_id": str(source_id),
            "regions": regions,
            "region_count": len(regions),
            "review_completed": bool(source.get("review_completed", False)),
        })
    return result


def _panel_semantics_for_region(
    workspace: str | Path,
    source: dict[str, Any],
    region: dict[str, Any],
) -> dict[str, str]:
    """Resolve post-training panel semantics without mutating detector GT.

    The panel profile is stored in normalized coordinates after the region model
    has been reviewed. Matching by the region centre makes the semantic role
    independent of the detector's transient table_id and tolerant of small box
    changes between the original GT and a later model prediction.
    """
    try:
        width = float(source.get("image_width") or 0)
        height = float(source.get("image_height") or 0)
        center_x = (float(region["x1"]) + float(region["x2"])) / 2.0
        center_y = (float(region["y1"]) + float(region["y2"])) / 2.0
    except (KeyError, TypeError, ValueError):
        return {}
    if width <= 0 or height <= 0:
        return {}

    try:
        from .table_panels import load_panel_profile
        profile = load_panel_profile(workspace)
    except (OSError, TypeError, ValueError):
        return {}

    nx, ny = center_x / width, center_y / height
    matches: list[tuple[float, dict[str, Any]]] = []
    for panel in profile.get("panels") or []:
        if not isinstance(panel, dict):
            continue
        try:
            x1, y1 = float(panel["x1"]), float(panel["y1"])
            x2, y2 = float(panel["x2"]), float(panel["y2"])
        except (KeyError, TypeError, ValueError):
            continue
        if x1 <= nx <= x2 and y1 <= ny <= y2:
            panel_center_x = (x1 + x2) / 2.0
            panel_center_y = (y1 + y2) / 2.0
            distance = (nx - panel_center_x) ** 2 + (ny - panel_center_y) ** 2
            matches.append((distance, panel))
    if not matches:
        return {}
    panel = min(matches, key=lambda item: item[0])[1]
    panel_id = str(panel.get("panel_id") or "").strip()
    if not panel_id:
        return {}
    return {
        "panel_id": panel_id,
        "panel_name": str(panel.get("name") or panel_id),
        # table_cell_training already consumes table_id as the crop/panel
        # identity. Expose the semantic role there without writing it into the
        # detector Ground Truth persisted on disk.
        "table_id": panel_id,
    }


def list_table_regions(workspace: str | Path, source_id: str) -> list[dict[str, Any]]:
    """Return regions enriched with post-training panel semantics when present."""
    source = next((item for item in list_table_region_sources(workspace) if item["source_id"] == str(source_id)), None)
    if not source:
        return []
    result: list[dict[str, Any]] = []
    for raw in source.get("regions") or []:
        if not isinstance(raw, dict):
            continue
        region = dict(raw)
        semantics = _panel_semantics_for_region(workspace, source, region)
        if semantics:
            region.update(semantics)
        result.append(region)
    return result


def clear_table_regions(workspace: str | Path, source_id: str) -> bool:
    """Remove the accepted table-region GT for one source before a fresh run."""
    root = resolve_project_workspace(workspace)
    payload = load_table_region_ground_truth(root)
    sources = payload.setdefault("sources", {})
    removed = str(source_id) in sources
    sources.pop(str(source_id), None)
    if removed:
        from datetime import datetime, timezone
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write(_path(root), payload)
    return removed


def save_table_regions(
    workspace: str | Path,
    source_id: str,
    *,
    image_width: int,
    image_height: int,
    regions: list[dict[str, Any]],
    allow_empty: bool = False,
) -> dict[str, Any]:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("De bronafmetingen moeten positief zijn")
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(regions):
        if not isinstance(raw, dict):
            continue
        try:
            x1 = max(0, min(image_width, int(round(float(raw["x1"])))));
            y1 = max(0, min(image_height, int(round(float(raw["y1"])))));
            x2 = max(0, min(image_width, int(round(float(raw["x2"])))));
            y2 = max(0, min(image_height, int(round(float(raw["y2"])))));
        except (KeyError, TypeError, ValueError):
            raise ValueError(f"Tabelregio {index + 1} heeft ongeldige coördinaten")
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Tabelregio {index + 1} is te klein")
        seed = f"table-region|{source_id}|{x1},{y1},{x2},{y2}"
        normalized.append({
            "region_id": "trg-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
            "source_id": str(source_id),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            # Keep detector GT semantic-free. The region dataset builder always
            # maps this geometry to its single class: table_region.
            "label": "table",
        })
    if not normalized and not allow_empty:
        raise ValueError("Teken minimaal één volledige tabelregio")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    root = resolve_project_workspace(workspace)
    payload = load_table_region_ground_truth(root)
    sources = payload.setdefault("sources", {})
    previous = sources.get(str(source_id)) if isinstance(sources.get(str(source_id)), dict) else {}
    sources[str(source_id)] = {
        **previous,
        "source_id": str(source_id),
        "image_width": int(image_width),
        "image_height": int(image_height),
        "regions": normalized,
        "review_completed": True,
        "updated_at": now,
    }
    payload["updated_at"] = now
    payload["schema_version"] = 1
    payload["type"] = "table_region_ground_truth"
    _write(_path(root), payload)
    return sources[str(source_id)]
