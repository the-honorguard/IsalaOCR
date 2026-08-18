from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .projects import resolve_project_workspace
from . import table_model_comparison as comparison
from . import table_cell_training as training

# A panel that failed in the newest completed review gets one extra draw. If the
# same panel is still wrong in consecutive model generations it can get two.
# Once a newer completed review is clean, its replay weight immediately returns
# to 1. A 150% replay budget is deliberate for the small, highly specific table
# datasets used here: recurrent/high-confidence failures must be allowed to use
# their full requested weight instead of being flattened to one extra draw.
MAX_REPLAY_WEIGHT = 3
REPLAY_BUDGET_RATIO = 1.50
HISTORY_LIMIT = 8

_ORIGINAL_LATEST_FEEDBACK = comparison.latest_completed_training_feedback
_ORIGINAL_BUILD_DATASET = training.build_table_cell_dataset
_INSTALLED = False


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, TypeError, ValueError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _panel_key(issue: dict[str, Any]) -> str:
    source_id = str(issue.get("source_id") or "")
    panel_id = str(issue.get("panel_id") or "")
    return f"{source_id}::{panel_id}" if source_id and panel_id else ""


def _completed_review_runs(root: Path) -> list[dict[str, Any]]:
    """Return completed comparison rounds, newest first, with panel-level errors."""
    reviews = comparison.comparison_reviews(root)
    runs_root = root / comparison.COMPARISON_DIRNAME / comparison.RUNS_DIRNAME
    if not runs_root.is_dir():
        return []

    result: list[dict[str, Any]] = []
    for path in runs_root.glob("*.json"):
        payload = _read_json(path, {}) or {}
        if not isinstance(payload, dict) or not payload.get("run_id"):
            continue
        run = comparison._current_evaluation_view(payload)
        run_id = str(run.get("run_id") or "")
        run_reviews = reviews.get(run_id, {}) if isinstance(reviews, dict) else {}
        run_reviews = run_reviews if isinstance(run_reviews, dict) else {}
        issues = [
            issue
            for panel in (run.get("panels") or [])
            if isinstance(panel, dict)
            for issue in (panel.get("issues") or [])
            if isinstance(issue, dict)
        ]

        resolved: list[tuple[dict[str, Any], dict[str, Any]]] = []
        complete = True
        for issue in issues:
            review = comparison._review_for_issue(issue, run_reviews) or {}
            decision = str(review.get("decision") or "")
            if not decision or decision == "deferred":
                complete = False
                break
            resolved.append((issue, review))
        if not complete:
            continue

        decision_counts: dict[str, int] = {}
        errors_by_panel: dict[str, list[dict[str, Any]]] = {}
        model_errors: list[dict[str, Any]] = []
        material: list[tuple[str, str]] = []
        for issue, review in resolved:
            decision = str(review.get("decision") or "")
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
            material.append((str(issue.get("issue_id") or ""), decision))
            if decision != "model_error":
                continue
            key = _panel_key(issue)
            if not key:
                continue
            try:
                confidence = float(issue.get("confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            item = {
                "issue_id": str(issue.get("issue_id") or ""),
                "type": str(issue.get("type") or ""),
                "source_id": str(issue.get("source_id") or ""),
                "panel_id": str(issue.get("panel_id") or ""),
                "confidence": max(0.0, min(1.0, confidence)),
            }
            errors_by_panel.setdefault(key, []).append(item)
            model_errors.append(item)

        result.append({
            "run_id": run_id,
            "model_id": str(run.get("model_id") or ""),
            "dataset_id": str(run.get("dataset_id") or ""),
            "created_at": str(run.get("created_at") or ""),
            "issue_count": len(issues),
            "decision_counts": decision_counts,
            "model_errors": model_errors,
            "errors_by_panel": errors_by_panel,
            "material": sorted(material),
        })

    result.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return result[:HISTORY_LIMIT]


def _feedback_from_completed_runs(completed: list[dict[str, Any]]) -> dict[str, Any]:
    if not completed:
        return {
            "available": False,
            "fingerprint": "",
            "model_error_count": 0,
            "model_errors": [],
            "panel_weights": {},
            "source_weights": {},
            "replay_panel_weights": {},
            "hard_example_registry": [],
        }

    latest = completed[0]
    latest_errors = latest.get("errors_by_panel") or {}
    latest_errors = latest_errors if isinstance(latest_errors, dict) else {}
    registry: list[dict[str, Any]] = []
    replay_panel_weights: dict[str, int] = {}

    for key, latest_items in sorted(latest_errors.items()):
        if not isinstance(latest_items, list) or not latest_items:
            continue
        streak = 0
        total_error_runs = 0
        still_consecutive = True
        for run in completed:
            run_errors = run.get("errors_by_panel") or {}
            has_error = isinstance(run_errors, dict) and bool(run_errors.get(key))
            if has_error:
                total_error_runs += 1
                if still_consecutive:
                    streak += 1
            elif still_consecutive:
                still_consecutive = False

        requested_weight = min(MAX_REPLAY_WEIGHT, 1 + max(1, streak))
        replay_panel_weights[key] = requested_weight
        source_id, panel_id = key.split("::", 1)
        error_types = sorted({str(item.get("type") or "") for item in latest_items if isinstance(item, dict)})
        max_confidence = max(
            [float(item.get("confidence") or 0.0) for item in latest_items if isinstance(item, dict)] or [0.0]
        )
        registry.append({
            "panel_key": key,
            "source_id": source_id,
            "panel_id": panel_id,
            "requested_weight": requested_weight,
            "error_streak": streak,
            "total_error_runs": total_error_runs,
            "latest_error_count": len(latest_items),
            "latest_error_types": error_types,
            "max_confidence": max_confidence,
            "latest_run_id": str(latest.get("run_id") or ""),
        })

    fingerprint_material = {
        "latest_run_id": str(latest.get("run_id") or ""),
        "completed_history": [
            {
                "run_id": str(run.get("run_id") or ""),
                "material": run.get("material") or [],
            }
            for run in completed
        ],
        "registry": registry,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    # Keep panel_weights empty on purpose. The canonical COCO builder used this
    # field for physical PNG duplication. The runtime sampler consumes
    # replay_panel_weights instead and performs additional draws in memory.
    return {
        "available": True,
        "run_id": str(latest.get("run_id") or ""),
        "model_id": str(latest.get("model_id") or ""),
        "dataset_id": str(latest.get("dataset_id") or ""),
        "created_at": str(latest.get("created_at") or ""),
        "fingerprint": fingerprint,
        "issue_count": int(latest.get("issue_count") or 0),
        "decision_counts": dict(latest.get("decision_counts") or {}),
        "model_error_count": len(latest.get("model_errors") or []),
        "model_errors": list(latest.get("model_errors") or []),
        "panel_weights": {},
        "source_weights": {},
        "replay_panel_weights": replay_panel_weights,
        "hard_example_registry": registry,
        "hard_example_registry_count": len(registry),
        "history_run_count": len(completed),
        "policy": (
            "dynamic panel hard-example replay; newest model_error panel -> weight 2; "
            "consecutive recurrence -> weight 3 max; recurrent/high-confidence panels get replay priority; "
            "a clean newer review resets to weight 1; train split only; no negative-only crops and no physical image copies"
        ),
    }


def _dynamic_hard_example_feedback(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    return _feedback_from_completed_runs(_completed_review_runs(root))


def _plan_replay(manifest: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
    train_panels = [
        dict(panel)
        for panel in (manifest.get("panels") or [])
        if isinstance(panel, dict) and str(panel.get("split") or "") == "train"
    ]
    by_key = {
        f"{str(panel.get('source_id') or '')}::{str(panel.get('panel_id') or '')}": panel
        for panel in train_panels
    }
    registry = {
        str(item.get("panel_key") or ""): dict(item)
        for item in (feedback.get("hard_example_registry") or [])
        if isinstance(item, dict)
    }
    requested_weights = {
        str(key): max(1, min(MAX_REPLAY_WEIGHT, int(value or 1)))
        for key, value in dict(feedback.get("replay_panel_weights") or {}).items()
        if str(key) in by_key
    }

    requested_extra = sum(max(0, weight - 1) for weight in requested_weights.values())
    budget = 0
    if requested_extra and train_panels:
        budget = max(1, int(len(train_panels) * REPLAY_BUDGET_RATIO))
        budget = min(budget, requested_extra)

    fingerprint = str(feedback.get("fingerprint") or "")
    slots: list[dict[str, Any]] = []
    for key, weight in requested_weights.items():
        meta = registry.get(key, {})
        for replay_index in range(1, weight):
            tie = hashlib.sha256(f"{fingerprint}|{key}|{replay_index}".encode("utf-8")).hexdigest()
            slots.append({
                "panel_key": key,
                "replay_index": replay_index,
                "error_streak": int(meta.get("error_streak") or 1),
                "latest_error_count": int(meta.get("latest_error_count") or 1),
                "max_confidence": float(meta.get("max_confidence") or 0.0),
                "tie": tie,
            })

    # Spend scarce replay budget on the failures that have survived the most
    # model generations, then on panels with multiple/high-confidence errors.
    # replay_index is deliberately a later tie-break: a persistent panel may get
    # its second extra draw before a one-off failure gets its first. This is the
    # key distinction between hard-example mining and uniform oversampling.
    slots.sort(key=lambda item: (
        -int(item["error_streak"]),
        -int(item["latest_error_count"]),
        -float(item["max_confidence"]),
        int(item["replay_index"]),
        str(item["tie"]),
    ))
    selected = slots[:budget]
    counts: dict[str, int] = {}
    for slot in selected:
        key = str(slot["panel_key"])
        counts[key] = counts.get(key, 0) + 1

    panels: list[dict[str, Any]] = []
    for key, replay_count in sorted(counts.items()):
        panel = by_key[key]
        meta = registry.get(key, {})
        panels.append({
            "panel_key": key,
            "source_id": str(panel.get("source_id") or ""),
            "panel_id": str(panel.get("panel_id") or ""),
            "panel_name": str(panel.get("panel_name") or panel.get("panel_id") or ""),
            "file_name": str(panel.get("file_name") or ""),
            "replay_count": replay_count,
            "effective_weight": 1 + replay_count,
            "requested_weight": int(requested_weights.get(key, 1)),
            "error_streak": int(meta.get("error_streak") or 1),
            "total_error_runs": int(meta.get("total_error_runs") or 1),
            "latest_error_count": int(meta.get("latest_error_count") or 1),
            "latest_error_types": list(meta.get("latest_error_types") or []),
            "max_confidence": float(meta.get("max_confidence") or 0.0),
        })

    return {
        "schema_version": 1,
        "strategy": "dynamic_panel_weighted_replay",
        "budget_ratio": REPLAY_BUDGET_RATIO,
        "base_train_panels": len(train_panels),
        "candidate_panel_count": len(requested_weights),
        "requested_extra_draws": requested_extra,
        "budget_extra_draws": budget,
        "selected_extra_draws": sum(counts.values()),
        "effective_train_draws": len(train_panels) + sum(counts.values()),
        "max_replay_weight": MAX_REPLAY_WEIGHT,
        "panels": panels,
    }


def _build_dataset_with_replay_plan(workspace: str | Path) -> dict[str, Any]:
    root = resolve_project_workspace(workspace)
    manifest = dict(_ORIGINAL_BUILD_DATASET(root))
    feedback = comparison.latest_completed_training_feedback(root)
    replay = _plan_replay(manifest, feedback)
    manifest["hard_example_panel_count"] = len(replay["panels"])
    # Deliberately zero: there are no physical hard-example PNG/COCO copies.
    manifest["hard_example_image_count"] = 0
    manifest["hard_example_replay_draw_count"] = int(replay["selected_extra_draws"])
    manifest["hard_example_replay"] = replay
    feedback_meta = dict(manifest.get("training_feedback") or {})
    feedback_meta.update({
        "hard_example_registry_count": int(feedback.get("hard_example_registry_count") or 0),
        "replay_candidate_panel_count": int(replay["candidate_panel_count"]),
        "replay_selected_extra_draws": int(replay["selected_extra_draws"]),
        "replay_budget_ratio": REPLAY_BUDGET_RATIO,
        "policy": str(feedback.get("policy") or ""),
    })
    manifest["training_feedback"] = feedback_meta
    dataset_root = root / str(manifest.get("path") or "")
    _write_json(dataset_root / "manifest.json", manifest)
    return manifest


def install_table_hard_example_replay_policy() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    comparison.latest_completed_training_feedback = _dynamic_hard_example_feedback
    training.build_table_cell_dataset = _build_dataset_with_replay_plan
    _INSTALLED = True


# Backwards-compatible import name used by v3.14.1 checkouts and tests.
def install_table_hard_negative_policy() -> None:
    install_table_hard_example_replay_policy()
