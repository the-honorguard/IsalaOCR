from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import Box
from .json_store import read_json_object, write_json_atomic

PANEL_PROFILE_VERSION = 2
PANEL_PROFILE_NAME = "table_panel_profile.json"

# load_panel_profile() re-reads the file and redoes panel/definition
# normalization on every call. table_region_ground_truth.py's
# _panel_semantics_for_region() calls it once per region, so a source with
# several table regions repeated this per source per page render. Cache by
# file signature (same convention as table_cell_ground_truth.py and
# table_region_ground_truth.py's caches).
#
# Reads get the cached object directly, not a copy - a deep copy on every
# read cost more than the work it replaced when called once per region in a
# loop (measured against table_cell_ground_truth.py's identical cache).
# Every caller here (in this file and elsewhere) only reads from the
# result and builds new dicts/lists from it; none mutate it in place.
_panel_profile_cache: dict[str, tuple[tuple[int, int] | None, dict[str, Any]]] = {}
_panel_profile_cache_lock = threading.Lock()


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or fallback


def panel_profile_path(workspace: str | Path) -> Path:
    return Path(workspace) / PANEL_PROFILE_NAME


def _write_profile(workspace: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    write_json_atomic(panel_profile_path(workspace), payload)
    return payload


def _normalize_definitions(raw_definitions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_definitions):
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or f"Panel {index + 1}").strip() or f"Panel {index + 1}"
        base_id = _slug(str(raw.get("panel_id") or name), f"panel-{index + 1}")
        panel_id = base_id
        suffix = 2
        while panel_id in used_ids:
            panel_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(panel_id)
        raw_hits = raw.get("hits") if isinstance(raw.get("hits"), list) else raw.get("aliases")
        hits = []
        for hit in raw_hits or []:
            value = str(hit or "").strip()
            if value and value.casefold() not in {item.casefold() for item in hits}:
                hits.append(value)
        definitions.append({"panel_id": panel_id, "name": name, "hits": hits})
    return definitions


def _normalize_panels(
    raw_panels: Iterable[dict[str, Any]],
    *,
    definitions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    definition_by_id = {str(item["panel_id"]): item for item in (definitions or [])}
    normalized: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for index, raw in enumerate(raw_panels):
        if not isinstance(raw, dict):
            continue
        try:
            x1 = max(0.0, min(1.0, float(raw.get("x1"))))
            y1 = max(0.0, min(1.0, float(raw.get("y1"))))
            x2 = max(0.0, min(1.0, float(raw.get("x2"))))
            y2 = max(0.0, min(1.0, float(raw.get("y2"))))
        except (TypeError, ValueError):
            raise ValueError(f"Panel {index + 1} heeft ongeldige coördinaten")
        if x2 - x1 < 0.01 or y2 - y1 < 0.01:
            raise ValueError(f"Panel {index + 1} is te klein")

        requested_id = str(raw.get("panel_id") or "").strip()
        if not requested_id and definitions and index < len(definitions):
            requested_id = str(definitions[index]["panel_id"])
        raw_name = str(raw.get("name") or "").strip()
        if requested_id and requested_id in definition_by_id:
            name = str(definition_by_id[requested_id]["name"])
            base_id = requested_id
        else:
            name = raw_name or f"Panel {index + 1}"
            base_id = _slug(requested_id or name, f"panel-{index + 1}")

        panel_id = base_id
        suffix = 2
        while panel_id in used_ids:
            panel_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(panel_id)
        normalized.append({
            "panel_id": panel_id,
            "name": name,
            "x1": round(x1, 6), "y1": round(y1, 6),
            "x2": round(x2, 6), "y2": round(y2, 6),
        })
    return normalized


def load_panel_profile(workspace: str | Path) -> dict[str, Any]:
    path = panel_profile_path(workspace)
    signature = _file_signature(path)
    key = str(path)
    with _panel_profile_cache_lock:
        cached = _panel_profile_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]

    if not path.is_file():
        result = {
            "schema_version": PANEL_PROFILE_VERSION,
            "mode": "manual",
            "definitions": [],
            "panels": [],
            "definitions_updated_at": "",
            "updated_at": "",
        }
    else:
        payload = read_json_object(path)

        # Existing v1 profiles did not have a separate setup list. Normalize panels
        # first, then derive one persistent definition per existing panel.
        panels = _normalize_panels(payload.get("panels") or [])
        raw_definitions = payload.get("definitions")
        if isinstance(raw_definitions, list) and raw_definitions:
            definitions = _normalize_definitions(raw_definitions)
        else:
            definitions = _normalize_definitions(
                {"panel_id": item.get("panel_id"), "name": item.get("name")} for item in panels
            )

        definition_by_id = {item["panel_id"]: item for item in definitions}
        synced_panels = []
        for panel in panels:
            item = dict(panel)
            definition = definition_by_id.get(str(item.get("panel_id") or ""))
            if definition:
                item["name"] = definition["name"]
            synced_panels.append(item)

        result = {
            "schema_version": int(payload.get("schema_version") or PANEL_PROFILE_VERSION),
            "mode": str(payload.get("mode") or "manual"),
            "reference_source_id": str(payload.get("reference_source_id") or ""),
            "reference_width": int(payload.get("reference_width") or 0),
            "reference_height": int(payload.get("reference_height") or 0),
            "definitions": definitions,
            "panels": synced_panels,
            "definitions_updated_at": str(payload.get("definitions_updated_at") or ""),
            "updated_at": str(payload.get("updated_at") or ""),
        }

    with _panel_profile_cache_lock:
        _panel_profile_cache[key] = (signature, result)
        if len(_panel_profile_cache) > 8:
            _panel_profile_cache.pop(next(iter(_panel_profile_cache)))
    return result


def save_panel_definitions(
    workspace: str | Path,
    *,
    definitions: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    existing = load_panel_profile(workspace)
    normalized = _normalize_definitions(definitions)
    if not normalized:
        raise ValueError("Voer minimaal één panelnaam in")

    existing_panels = list(existing.get("panels") or [])
    old_by_id = {str(item.get("panel_id") or ""): item for item in existing_panels}
    new_ids = {item["panel_id"] for item in normalized}
    geometry_changed = any(panel_id not in new_ids for panel_id in old_by_id)
    semantics_changed = any(
        old_by_id.get(definition["panel_id"])
        and str(old_by_id[definition["panel_id"]].get("name") or "") != definition["name"]
        for definition in normalized
    )

    panels = []
    for definition in normalized:
        old = old_by_id.get(definition["panel_id"])
        if old:
            panels.append({**old, "name": definition["name"]})

    payload = {
        **existing,
        "schema_version": PANEL_PROFILE_VERSION,
        "definitions": normalized,
        "panels": panels,
        "definitions_updated_at": _utcnow(),
    }
    # Panel names are semantic identifiers used later in table/mapping metadata.
    # Renaming or removing an already-positioned panel therefore makes the prior
    # table run stale even when the numeric geometry did not change.
    if geometry_changed or semantics_changed:
        payload["updated_at"] = _utcnow()
    return _write_profile(workspace, payload)


def save_panel_profile(
    workspace: str | Path,
    *,
    panels: Iterable[dict[str, Any]],
    reference_source_id: str = "",
    reference_width: int = 0,
    reference_height: int = 0,
    mode: str = "manual",
) -> dict[str, Any]:
    existing = load_panel_profile(workspace)
    definitions = list(existing.get("definitions") or [])
    normalized = _normalize_panels(panels, definitions=definitions or None)
    if not normalized:
        raise ValueError("Teken minimaal één table-panel voordat je opslaat")

    if definitions:
        required = {str(item["panel_id"]) for item in definitions}
        positioned = {str(item["panel_id"]) for item in normalized}
        missing = [item["name"] for item in definitions if item["panel_id"] not in positioned]
        extra = positioned - required
        if missing:
            raise ValueError("Teken eerst alle ingestelde panelen: " + ", ".join(missing))
        if extra:
            raise ValueError("Er staan panelkaders zonder ingestelde panelnaam. Pas de panelnamen eerst aan in Stap 1.")
    else:
        definitions = _normalize_definitions(
            {"panel_id": item["panel_id"], "name": item["name"]} for item in normalized
        )

    payload = {
        "schema_version": PANEL_PROFILE_VERSION,
        "mode": mode,
        "reference_source_id": reference_source_id,
        "reference_width": int(reference_width or 0),
        "reference_height": int(reference_height or 0),
        "definitions": definitions,
        "panels": normalized,
        "definitions_updated_at": str(existing.get("definitions_updated_at") or _utcnow()),
        "updated_at": _utcnow(),
    }
    return _write_profile(workspace, payload)


def clear_panel_geometry(workspace: str | Path) -> dict[str, Any]:
    existing = load_panel_profile(workspace)
    payload = {
        **existing,
        "schema_version": PANEL_PROFILE_VERSION,
        "panels": [],
        "updated_at": _utcnow(),
    }
    return _write_profile(workspace, payload)


def panel_boxes_for_image(profile: dict[str, Any], width: int, height: int) -> list[dict[str, Any]]:
    result = []
    for raw in profile.get("panels") or []:
        try:
            x1 = int(round(float(raw["x1"]) * width)); y1 = int(round(float(raw["y1"]) * height))
            x2 = int(round(float(raw["x2"]) * width)); y2 = int(round(float(raw["y2"]) * height))
        except (KeyError, TypeError, ValueError):
            continue
        x1 = max(0, min(width - 1, x1)); y1 = max(0, min(height - 1, y1))
        x2 = max(x1 + 1, min(width, x2)); y2 = max(y1 + 1, min(height, y2))
        box = Box(x1, y1, x2, y2)
        result.append({
            "panel_id": str(raw.get("panel_id") or f"panel-{len(result)+1}"),
            "name": str(raw.get("name") or f"Panel {len(result)+1}"),
            "box": box,
        })
    return result
