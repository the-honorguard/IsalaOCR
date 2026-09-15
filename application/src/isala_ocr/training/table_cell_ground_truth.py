from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from typing import Any

from .db import TrainingDatabase, utc_now
from .projects import resolve_project_workspace
from .json_store import read_json as _read_json, write_json_atomic as _write_json

GROUND_TRUTH_FILENAME = "table_cell_ground_truth.json"

# This file is often the whole canonical GT for a project - every reviewed
# source and cell - and load_table_cell_ground_truth() used to reload and
# re-parse it from disk on every single call. Several callers (notably
# table_cell_training.py's _dataset_source_state()) called it once per
# source in a loop, and it's on the request path of nearly every page in
# table-first mode via canonical_table_gt_mode()/process_snapshot(). Cache
# by file signature (mtime+size), the same convention already used by
# registry_state() and ProjectManager._catalog().
#
# Reads get the cached object directly, not a copy: a deep copy of a large
# payload just to read a handful of fields (or one source's slice, in a
# per-source loop) turned out to cost *more* than the disk read + JSON parse
# it was meant to save - measured 2x slower against a 100-source/500-cell
# ground truth. Every read-only caller here only ever builds new dicts/lists
# from what it reads and never mutates the returned structure in place, so
# this is safe; the one place that does mutate in place (_mutate(), below)
# is responsible for its own deep copy before touching anything.
_ground_truth_cache: dict[str, tuple[tuple[int, int] | None, dict[str, Any] | None]] = {}
_ground_truth_cache_lock = threading.Lock()


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def ground_truth_path(workspace: str | Path) -> Path:
    return resolve_project_workspace(workspace) / GROUND_TRUTH_FILENAME


def load_table_cell_ground_truth(workspace: str | Path) -> dict[str, Any] | None:
    path = ground_truth_path(workspace)
    signature = _file_signature(path)
    key = str(path)
    with _ground_truth_cache_lock:
        cached = _ground_truth_cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]

    payload = _read_json(path, None)
    if not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
        result = None
    else:
        sources = payload.get("sources")
        result = payload if isinstance(sources, dict) else None

    with _ground_truth_cache_lock:
        _ground_truth_cache[key] = (signature, result)
        if len(_ground_truth_cache) > 8:
            _ground_truth_cache.pop(next(iter(_ground_truth_cache)))
    return result


def _latest_dataset_root(root: Path) -> tuple[str, Path] | None:
    pointer = root / "table_cell_datasets" / "latest.txt"
    if not pointer.is_file():
        return None
    dataset_id = pointer.read_text(encoding="utf-8-sig").strip()
    if not dataset_id:
        return None
    dataset_root = root / "table_cell_datasets" / dataset_id
    if not dataset_root.is_dir():
        return None
    return dataset_id, dataset_root


def bootstrap_table_cell_ground_truth(workspace: str | Path, *, force: bool = False) -> dict[str, Any] | None:
    """Create the editable canonical GT from the latest frozen table-cell dataset.

    Once created this file is authoritative for Step 4 and future dataset builds.
    Later Step-3 detector runs never overwrite it.
    """
    root = resolve_project_workspace(workspace)
    existing = load_table_cell_ground_truth(root)
    if existing is not None and not force:
        return existing
    latest = _latest_dataset_root(root)
    if latest is None:
        return None
    dataset_id, dataset_root = latest
    manifest = _read_json(dataset_root / "manifest.json", {}) or {}
    panels = manifest.get("panels") if isinstance(manifest, dict) else []
    panels = panels if isinstance(panels, list) else []

    image_annotations: dict[str, list[dict[str, Any]]] = {}
    for split in ("train", "val", "test"):
        coco = _read_json(dataset_root / "annotations" / f"instance_{split}.json", {}) or {}
        images = coco.get("images") if isinstance(coco, dict) else []
        annotations = coco.get("annotations") if isinstance(coco, dict) else []
        images = images if isinstance(images, list) else []
        annotations = annotations if isinstance(annotations, list) else []
        image_by_id = {
            int(item["id"]): item for item in images
            if isinstance(item, dict) and item.get("id") is not None
        }
        for ann in annotations:
            if not isinstance(ann, dict) or not isinstance(ann.get("bbox"), list) or len(ann["bbox"]) != 4:
                continue
            image = image_by_id.get(int(ann.get("image_id") or -1))
            if not image:
                continue
            try:
                x, y, w, h = (float(value) for value in ann["bbox"])
            except (TypeError, ValueError):
                continue
            if w <= 0 or h <= 0:
                continue
            filename = str(image.get("file_name") or "")
            image_annotations.setdefault(filename, []).append({
                "split": split,
                "coco_annotation_id": ann.get("id"),
                "box": [x, y, x + w, y + h],
            })

    sources: dict[str, dict[str, Any]] = {}
    seen_cells: set[tuple[str, int, int, int, int]] = set()
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        source_id = str(panel.get("source_id") or "").strip()
        filename = str(panel.get("file_name") or "").strip()
        box = panel.get("box")
        if not source_id or not filename or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            px1, py1, px2, py2 = (int(round(float(value))) for value in box)
        except (TypeError, ValueError):
            continue
        source = sources.setdefault(source_id, {
            "source_id": source_id,
            "split": str(panel.get("split") or "train"),
            "cells": [],
            # The canonical GT is bootstrapped from a dataset that could only
            # have been built from completed source reviews.  Keep that
            # completion state with the GT itself so later detector runs cannot
            # reset it in SQLite.
            "review_completed": True,
            "review_completed_at": str(manifest.get("created_at") or utc_now()),
        })
        for ann in image_annotations.get(filename, []):
            lx1, ly1, lx2, ly2 = ann["box"]
            x1 = int(round(px1 + lx1)); y1 = int(round(py1 + ly1))
            x2 = int(round(px1 + lx2)); y2 = int(round(py1 + ly2))
            key = (source_id, x1, y1, x2, y2)
            if key in seen_cells:
                continue
            seen_cells.add(key)
            seed = f"{dataset_id}|{source_id}|{panel.get('panel_id')}|{ann.get('split')}|{ann.get('coco_annotation_id')}|{x1},{y1},{x2},{y2}"
            gt_id = "gt-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
            source["cells"].append({
                "gt_id": gt_id,
                "source_id": source_id,
                "panel_id": str(panel.get("panel_id") or ""),
                "panel_name": str(panel.get("panel_name") or panel.get("panel_id") or ""),
                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                "provenance": "step4_baseline",
                "created_at": str(manifest.get("created_at") or utc_now()),
                "updated_at": str(manifest.get("created_at") or utc_now()),
            })

    now = utc_now()
    payload = {
        "schema_version": 1,
        "type": "canonical_table_cell_ground_truth",
        "base_dataset_id": dataset_id,
        "base_review_fingerprint": str(manifest.get("review_fingerprint") or ""),
        "created_at": now,
        "updated_at": now,
        "revision": 1,
        "sources": sources,
    }
    _write_json(root / GROUND_TRUTH_FILENAME, payload)
    return payload


def ensure_table_cell_ground_truth(workspace: str | Path) -> dict[str, Any] | None:
    return load_table_cell_ground_truth(workspace) or bootstrap_table_cell_ground_truth(workspace)


def ground_truth_counts(workspace: str | Path, source_id: str | None = None) -> dict[str, int]:
    payload = ensure_table_cell_ground_truth(workspace)
    if payload is None:
        return {"source_count": 0, "positive": 0, "candidate_total": 0, "pending": 0, "added": 0}
    sources = payload.get("sources") or {}
    selected = [sources.get(source_id)] if source_id is not None else list(sources.values())
    selected = [item for item in selected if isinstance(item, dict)]
    total = sum(len(item.get("cells") or []) for item in selected)
    return {
        "source_count": len(selected),
        "correct": total,
        "adjusted": 0,
        "rejected": 0,
        "relevant": total,
        "irrelevant": 0,
        "added": 0,
        "candidate_total": total,
        "candidate_reviewed": total,
        "pending": 0,
        "positive": total,
        "negative": 0,
        "ignored": 0,
        "persistent": total,
        "total_reviews": total,
    }


def list_ground_truth_sources(workspace: str | Path) -> list[dict[str, Any]]:
    payload = ensure_table_cell_ground_truth(workspace)
    if payload is None:
        return []
    result = []
    for source_id, source in sorted((payload.get("sources") or {}).items()):
        if not isinstance(source, dict):
            continue
        result.append({
            **source,
            "source_id": source_id,
            "gt_count": len(source.get("cells") or []),
            # v3.13.1-v3.13.9 canonical files predate this field.  Those GTs
            # were created from an already completed dataset, so missing means
            # completed for backward compatibility.
            "review_completed": bool(source.get("review_completed", True)),
            "review_completed_at": source.get("review_completed_at"),
        })
    return result


def set_ground_truth_source_review_completed(
    workspace: str | Path, source_id: str, completed: bool = True
) -> dict[str, Any]:
    """Persist image-level review state on the canonical GT itself.

    This deliberately does *not* increment the geometry revision: checking an
    image does not change training geometry and must not make an otherwise
    current dataset stale.
    """
    root = resolve_project_workspace(workspace)
    payload = ensure_table_cell_ground_truth(root)
    if payload is None:
        raise FileNotFoundError("Er is nog geen canonieke table-cell Ground Truth")
    source = (payload.get("sources") or {}).get(source_id)
    if not isinstance(source, dict):
        raise KeyError(source_id)
    now = utc_now()
    source["review_completed"] = bool(completed)
    source["review_completed_at"] = now if completed else None
    payload["updated_at"] = now
    _write_json(root / GROUND_TRUTH_FILENAME, payload)
    return {
        **source,
        "source_id": source_id,
        "gt_count": len(source.get("cells") or []),
        "review_completed": bool(source.get("review_completed")),
    }


def ground_truth_review_state(workspace: str | Path) -> dict[str, Any]:
    sources = list_ground_truth_sources(workspace)
    completed = sum(1 for item in sources if bool(item.get("review_completed")))
    return {
        "source_count": len(sources),
        "completed_source_count": completed,
        "open_source_count": max(0, len(sources) - completed),
        "gt_cell_count": sum(int(item.get("gt_count") or 0) for item in sources),
        "sources": sources,
        "ready": bool(sources) and completed == len(sources),
    }


def canonical_detection_gate_state(workspace: str | Path) -> dict[str, Any]:
    """Ready/reason for the canonical table-cell GT detection gate.

    Split out of ``table_first_cli.py``'s ``_sync_table_first_gate()`` and
    ``mapping_gt_cli.py``'s ``_sync_canonical_gate()``, which computed the
    exact same ready/reason logic independently (CODE_REVIEW_v3.16.0.md,
    sectie Middel: "Detectiegate-synclogica letterlijk gekopieerd").
    """
    state = ground_truth_review_state(workspace)
    source_count = int(state.get("source_count") or 0)
    open_source_count = int(state.get("open_source_count") or 0)
    gt_cell_count = int(state.get("gt_cell_count") or 0)
    ready = bool(source_count > 0 and gt_cell_count > 0 and open_source_count == 0)
    if ready:
        reason = (
            f"Canonical table-cell Ground Truth ready: {source_count} source(s), "
            f"{gt_cell_count} cell(s), 0 open GT source(s)."
        )
    elif source_count == 0 or gt_cell_count == 0:
        reason = "Canonical table-cell Ground Truth is missing or contains no cells."
    else:
        reason = (
            f"Canonical table-cell Ground Truth still has {open_source_count} open "
            f"source(s) out of {source_count}."
        )
    return {**state, "ready": ready, "reason": reason}


def sync_canonical_detection_gate(workspace: str | Path) -> dict[str, Any]:
    """Compute the canonical detection-gate state and persist it to TrainingDatabase.

    Split out of the same two CLI entrypoints as
    ``canonical_detection_gate_state()`` above.
    """
    workspace = Path(workspace)
    state = canonical_detection_gate_state(workspace)
    TrainingDatabase(workspace / "samples.sqlite3").set_detection_gate(
        bool(state["ready"]), reason=str(state["reason"]), evaluation_id="",
    )
    return state


def list_ground_truth_cells(workspace: str | Path, source_id: str) -> list[dict[str, Any]]:
    payload = ensure_table_cell_ground_truth(workspace)
    if payload is None:
        return []
    source = (payload.get("sources") or {}).get(source_id)
    if not isinstance(source, dict):
        return []
    return [dict(item) for item in source.get("cells") or [] if isinstance(item, dict)]


def _mutate(workspace: str | Path, mutator) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    payload = ensure_table_cell_ground_truth(root)
    if payload is None:
        raise FileNotFoundError("Er is nog geen canonieke table-cell Ground Truth")
    # load_table_cell_ground_truth() returns the cached object directly (see
    # its docstring comment) - copy before mutating so this never corrupts
    # the cache for a concurrent reader.
    payload = copy.deepcopy(payload)
    result = mutator(payload)
    payload["revision"] = int(payload.get("revision") or 0) + 1
    payload["updated_at"] = utc_now()
    _write_json(root / GROUND_TRUTH_FILENAME, payload)
    return result


def add_ground_truth_cell(
    workspace: str | Path,
    source_id: str,
    box: tuple[int, int, int, int],
    *,
    panel_id: str = "",
    panel_name: str = "",
    provenance: str = "manual_gt",
) -> dict[str, Any]:
    x1, y1, x2, y2 = (int(v) for v in box)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Ground Truth-kader moet een positieve breedte en hoogte hebben")
    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        sources = payload.setdefault("sources", {})
        source = sources.setdefault(source_id, {
            "source_id": source_id, "split": "train", "cells": [],
            "review_completed": False, "review_completed_at": None,
        })
        # Any geometry edit means this source needs one explicit visual GT check
        # again before it is considered complete.
        source["review_completed"] = False
        source["review_completed_at"] = None
        now = utc_now()
        seed = f"{provenance}|{source_id}|{panel_id}|{x1},{y1},{x2},{y2}|{now}"
        cell = {
            "gt_id": "gt-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24],
            "source_id": source_id,
            "panel_id": str(panel_id or ""),
            "panel_name": str(panel_name or panel_id or ""),
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "provenance": str(provenance or "manual_gt"),
            "created_at": now, "updated_at": now,
        }
        source.setdefault("cells", []).append(cell)
        return dict(cell)
    return _mutate(workspace, apply)


def update_ground_truth_cell(workspace: str | Path, source_id: str, gt_id: str, box: tuple[int, int, int, int]) -> dict[str, Any]:
    x1, y1, x2, y2 = (int(v) for v in box)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("Ground Truth-kader moet een positieve breedte en hoogte hebben")
    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        source = (payload.get("sources") or {}).get(source_id)
        if not isinstance(source, dict):
            raise KeyError(gt_id)
        for cell in source.get("cells") or []:
            if str(cell.get("gt_id") or "") == gt_id:
                cell.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "updated_at": utc_now()})
                source["review_completed"] = False
                source["review_completed_at"] = None
                return dict(cell)
        raise KeyError(gt_id)
    return _mutate(workspace, apply)


def delete_ground_truth_cell(workspace: str | Path, source_id: str, gt_id: str) -> None:
    def apply(payload: dict[str, Any]) -> dict[str, Any]:
        source = (payload.get("sources") or {}).get(source_id)
        if not isinstance(source, dict):
            raise KeyError(gt_id)
        cells = source.get("cells") or []
        for index, cell in enumerate(cells):
            if str(cell.get("gt_id") or "") == gt_id:
                cells.pop(index)
                source["review_completed"] = False
                source["review_completed_at"] = None
                return {"gt_id": gt_id}
        raise KeyError(gt_id)
    _mutate(workspace, apply)
