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
    payload = load_table_region_ground_truth(workspace)
    result: list[dict[str, Any]] = []
    for source_id, source in sorted((payload.get("sources") or {}).items()):
        if not isinstance(source, dict):
            continue
        regions = [item for item in source.get("regions") or [] if isinstance(item, dict)]
        result.append({
            **source,
            "source_id": str(source_id),
            "regions": regions,
            "region_count": len(regions),
            "review_completed": bool(source.get("review_completed", False)),
        })
    return result


def list_table_regions(workspace: str | Path, source_id: str) -> list[dict[str, Any]]:
    source = next((item for item in list_table_region_sources(workspace) if item["source_id"] == str(source_id)), None)
    return list(source.get("regions") or []) if source else []


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
            "label": str(raw.get("name") or "table"),
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
