from __future__ import annotations

from pathlib import Path

from isala_ocr.training.table_hard_negative_policy import (
    MAX_REPLAY_WEIGHT,
    REPLAY_BUDGET_RATIO,
    _feedback_from_completed_runs,
    _plan_replay,
)


ROOT = Path(__file__).resolve().parents[1]


def _error(source: str, panel: str, *, issue_type: str = "fp", confidence: float = 0.9) -> dict:
    return {
        "issue_id": f"{source}-{panel}-{issue_type}",
        "type": issue_type,
        "source_id": source,
        "panel_id": panel,
        "confidence": confidence,
    }


def _run(run_id: str, errors: dict[str, list[dict]]) -> dict:
    model_errors = [item for values in errors.values() for item in values]
    return {
        "run_id": run_id,
        "model_id": f"model-{run_id}",
        "dataset_id": f"dataset-{run_id}",
        "created_at": run_id,
        "issue_count": len(model_errors),
        "decision_counts": {"model_error": len(model_errors)} if model_errors else {},
        "model_errors": model_errors,
        "errors_by_panel": errors,
        "material": sorted((item["issue_id"], "model_error") for item in model_errors),
    }


def test_recurrent_panel_gets_more_replay_weight_than_new_error() -> None:
    panel_a = "source-a::left"
    panel_b = "source-b::right"
    completed = [
        _run("2026-08-18T10:00:00+00:00", {
            panel_a: [_error("source-a", "left", confidence=0.97)],
            panel_b: [_error("source-b", "right", issue_type="geometry", confidence=0.75)],
        }),
        _run("2026-08-18T09:00:00+00:00", {
            panel_a: [_error("source-a", "left", confidence=0.94)],
        }),
    ]

    feedback = _feedback_from_completed_runs(completed)

    assert feedback["panel_weights"] == {}
    assert feedback["replay_panel_weights"][panel_a] == MAX_REPLAY_WEIGHT == 3
    assert feedback["replay_panel_weights"][panel_b] == 2
    registry = {item["panel_key"]: item for item in feedback["hard_example_registry"]}
    assert registry[panel_a]["error_streak"] == 2
    assert registry[panel_b]["error_streak"] == 1
    assert "replay priority" in feedback["policy"]
    assert "no negative-only crops" in feedback["policy"]


def test_newer_clean_review_immediately_clears_old_hard_example() -> None:
    panel_a = "source-a::left"
    completed = [
        _run("2026-08-18T10:00:00+00:00", {}),
        _run("2026-08-18T09:00:00+00:00", {panel_a: [_error("source-a", "left")]}),
    ]

    feedback = _feedback_from_completed_runs(completed)

    assert feedback["available"] is True
    assert feedback["model_error_count"] == 0
    assert feedback["replay_panel_weights"] == {}
    assert feedback["hard_example_registry"] == []


def test_replay_plan_is_train_only_and_budgeted() -> None:
    feedback = {
        "fingerprint": "round-1",
        "replay_panel_weights": {
            "source-a::left": 3,
            "source-b::right": 2,
            "source-val::left": 3,
        },
        "hard_example_registry": [
            {"panel_key": "source-a::left", "error_streak": 2, "latest_error_count": 2, "max_confidence": 0.99},
            {"panel_key": "source-b::right", "error_streak": 1, "latest_error_count": 1, "max_confidence": 0.85},
            {"panel_key": "source-val::left", "error_streak": 4, "latest_error_count": 4, "max_confidence": 1.0},
        ],
    }
    manifest = {
        "panels": [
            {"source_id": "source-a", "panel_id": "left", "panel_name": "A", "file_name": "a.png", "split": "train"},
            {"source_id": "source-b", "panel_id": "right", "panel_name": "B", "file_name": "b.png", "split": "train"},
            {"source_id": "source-c", "panel_id": "left", "panel_name": "C", "file_name": "c.png", "split": "train"},
            {"source_id": "source-d", "panel_id": "right", "panel_name": "D", "file_name": "d.png", "split": "train"},
            {"source_id": "source-val", "panel_id": "left", "panel_name": "V", "file_name": "v.png", "split": "val"},
        ]
    }

    plan = _plan_replay(manifest, feedback)

    assert plan["strategy"] == "dynamic_panel_weighted_replay"
    assert plan["base_train_panels"] == 4
    assert plan["budget_extra_draws"] == min(3, int(4 * REPLAY_BUDGET_RATIO)) == 3
    assert plan["selected_extra_draws"] == 3
    assert plan["effective_train_draws"] == 7
    assert {item["panel_key"] for item in plan["panels"]} == {"source-a::left", "source-b::right"}
    replay_counts = {item["panel_key"]: item["replay_count"] for item in plan["panels"]}
    assert replay_counts == {"source-a::left": 2, "source-b::right": 1}
    assert all(item["source_id"] != "source-val" for item in plan["panels"])


def test_scarce_budget_prioritizes_recurrent_high_confidence_panel() -> None:
    panel_keys = [f"source-{name}::left" for name in "abcd"]
    feedback = {
        "fingerprint": "priority-round",
        "replay_panel_weights": {key: 3 for key in panel_keys},
        "hard_example_registry": [
            {"panel_key": panel_keys[0], "error_streak": 6, "latest_error_count": 2, "max_confidence": 0.98},
            {"panel_key": panel_keys[1], "error_streak": 2, "latest_error_count": 1, "max_confidence": 0.90},
            {"panel_key": panel_keys[2], "error_streak": 1, "latest_error_count": 1, "max_confidence": 0.88},
            {"panel_key": panel_keys[3], "error_streak": 1, "latest_error_count": 1, "max_confidence": 0.80},
        ],
    }
    manifest = {
        "panels": [
            {
                "source_id": f"source-{name}",
                "panel_id": "left",
                "panel_name": name.upper(),
                "file_name": f"{name}.png",
                "split": "train",
            }
            for name in "abcd"
        ]
    }

    plan = _plan_replay(manifest, feedback)
    replay_counts = {item["panel_key"]: item["replay_count"] for item in plan["panels"]}

    assert plan["requested_extra_draws"] == 8
    assert plan["budget_extra_draws"] == int(4 * REPLAY_BUDGET_RATIO) == 6
    assert replay_counts[panel_keys[0]] == 2
    assert replay_counts[panel_keys[1]] == 2
    assert replay_counts[panel_keys[3]] <= 1


def test_policy_no_longer_generates_negative_crops_or_duplicate_pngs() -> None:
    source = (ROOT / "application" / "src" / "isala_ocr" / "training" / "table_hard_negative_policy.py").read_text(encoding="utf-8")

    assert "from PIL" not in source
    assert "crop.save" not in source
    assert "HARD_NEGATIVE_COPIES" not in source
    assert "negative-only crops x3" not in source
    assert '"panel_weights": {}' in source
    assert "dynamic_panel_weighted_replay" in source
