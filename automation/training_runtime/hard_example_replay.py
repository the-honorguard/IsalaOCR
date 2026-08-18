from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

REPLAY_STRATEGY = "dynamic_panel_weighted_replay"


def load_replay_plan(dataset: str | Path) -> dict[str, Any]:
    """Load the training-only hard-example replay plan from a dataset manifest."""
    root = Path(dataset).resolve()
    manifest_path = root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError):
        return {"strategy": REPLAY_STRATEGY, "selected_extra_draws": 0, "panels": []}
    if not isinstance(manifest, dict):
        return {"strategy": REPLAY_STRATEGY, "selected_extra_draws": 0, "panels": []}
    replay = manifest.get("hard_example_replay")
    if not isinstance(replay, dict) or str(replay.get("strategy") or "") != REPLAY_STRATEGY:
        return {"strategy": REPLAY_STRATEGY, "selected_extra_draws": 0, "panels": []}
    panels = [dict(item) for item in (replay.get("panels") or []) if isinstance(item, dict)]
    selected = sum(max(0, int(item.get("replay_count") or 0)) for item in panels)
    result = dict(replay)
    result["panels"] = panels
    result["selected_extra_draws"] = selected
    return result


def replay_training_counts(dataset: str | Path, *, base_images: int) -> dict[str, int]:
    plan = load_replay_plan(dataset)
    extra = max(0, int(plan.get("selected_extra_draws") or 0))
    return {
        "base_train_images": max(0, int(base_images)),
        "hard_example_replay_draws": extra,
        "effective_train_images": max(0, int(base_images)) + extra,
    }


def _record_filename(record: dict[str, Any]) -> str:
    return Path(str(record.get("im_file") or "")).name


def _next_image_id(records: list[dict[str, Any]]) -> int:
    maximum = 0
    for record in records:
        raw = record.get("im_id")
        try:
            if hasattr(raw, "tolist"):
                raw = raw.tolist()
            if isinstance(raw, (list, tuple)):
                raw = raw[0] if raw else 0
            maximum = max(maximum, int(raw or 0))
        except (TypeError, ValueError):
            continue
    return maximum + 1


def _replace_image_id(record: dict[str, Any], value: int) -> None:
    raw = record.get("im_id")
    try:
        import numpy as np

        dtype = getattr(raw, "dtype", None)
        record["im_id"] = np.array([value], dtype=dtype) if dtype is not None else np.array([value])
    except Exception:
        record["im_id"] = [value]


def apply_replay_to_records(
    records: list[dict[str, Any]], dataset: str | Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Apply weighted panel replay in memory without duplicating image files.

    PaddleDetection's normal DistributedBatchSampler shuffles ``roidbs`` every
    epoch. Adding references to the same panel record therefore gives a hard
    panel additional independent draws/augmentations while the canonical COCO
    dataset and PNG files remain single-copy and auditable.

    Replay clones intentionally keep exactly the same sample-key schema as the
    canonical COCO records. PaddleDetection's batch collator takes the keys from
    one sample and indexes every other sample with those keys; adding replay-only
    metadata fields therefore crashes mixed batches with a KeyError. Runtime
    replay diagnostics are written separately by ``sitecustomize.py``.
    """
    base = list(records)
    plan = load_replay_plan(dataset)
    panels = [item for item in (plan.get("panels") or []) if int(item.get("replay_count") or 0) > 0]
    expected = sum(int(item.get("replay_count") or 0) for item in panels)
    if expected <= 0:
        return base, {
            "strategy": REPLAY_STRATEGY,
            "base_records": len(base),
            "extra_draws": 0,
            "effective_records": len(base),
            "panel_count": 0,
        }

    by_filename = {_record_filename(record): record for record in base if _record_filename(record)}
    missing = sorted({str(item.get("file_name") or "") for item in panels if str(item.get("file_name") or "") not in by_filename})
    if missing:
        raise RuntimeError(
            "Hard-example replay verwijst naar train-panelen die PaddleDetection niet heeft geladen: "
            + ", ".join(missing[:8])
        )

    result = list(base)
    next_image_id = _next_image_id(base)
    applied = 0
    for item in panels:
        filename = str(item.get("file_name") or "")
        source = by_filename[filename]
        for _replay_index in range(1, int(item.get("replay_count") or 0) + 1):
            clone = copy.deepcopy(source)
            _replace_image_id(clone, next_image_id)
            next_image_id += 1
            # Do not add replay-only keys to the record. Mixed batches must have
            # one identical key schema for PaddleDetection's BatchCompose.
            result.append(clone)
            applied += 1

    if applied != expected:
        raise RuntimeError(f"Hard-example replay verwachtte {expected} extra draws maar maakte er {applied}")
    return result, {
        "strategy": REPLAY_STRATEGY,
        "base_records": len(base),
        "extra_draws": applied,
        "effective_records": len(result),
        "panel_count": len(panels),
        "budget_ratio": float(plan.get("budget_ratio") or 0.0),
        "candidate_panel_count": int(plan.get("candidate_panel_count") or 0),
        "requested_extra_draws": int(plan.get("requested_extra_draws") or 0),
    }
