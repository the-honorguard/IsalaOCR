from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.table_cell_training import register_table_cell_model, table_cell_model_history


def _register(tmp_path: Path, model_id: str, created_order: int, evaluation: dict) -> None:
    inference = tmp_path / "runs" / model_id / "inference"
    inference.mkdir(parents=True)
    (inference / "inference.yml").write_text("model: table\n", encoding="utf-8")
    register_table_cell_model(
        tmp_path, model_id=model_id, run_id=f"run-{model_id}", dataset_id=f"dataset-{model_id}",
        inference_dir=inference, device="gpu", evaluation=evaluation,
    )
    # register_table_cell_model stamps created_at with utc_now(); force a
    # deterministic order for the trend regardless of how fast the test runs.
    model_json = tmp_path / "table_cell_models" / model_id / "model.json"
    payload = json.loads(model_json.read_text(encoding="utf-8"))
    payload["created_at"] = f"2026-01-{created_order:02d}T00:00:00+00:00"
    model_json.write_text(json.dumps(payload), encoding="utf-8")


def test_history_flags_a_saturated_streak_across_registered_models(tmp_path: Path) -> None:
    _register(tmp_path, "m1", 1, {
        "precision": 0.9, "recall": 0.8, "f1": 0.85, "panel_count": 10, "saturated": False,
    })
    _register(tmp_path, "m2", 2, {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "panel_count": 10,
        "saturated": True, "strictest_clean_iou_threshold": 0.85,
    })
    _register(tmp_path, "m3", 3, {
        "precision": 1.0, "recall": 1.0, "f1": 1.0, "panel_count": 10,
        "saturated": True, "strictest_clean_iou_threshold": 0.65,
    })

    history = table_cell_model_history(tmp_path)

    assert history["model_count"] == 3
    assert [row["model_id"] for row in history["models"]] == ["m1", "m2", "m3"]
    assert history["saturated_streak"] == 2
    assert "saturated" in history["note"]
    # Two runs in a row report the same saturated 1.0 top-line score, but the
    # stricter companion metric shows m3 is actually weaker evidence than m2 --
    # exactly the kind of hidden regression the plain history should surface.
    assert [row["strictest_clean_iou_threshold"] for row in history["models"][-2:]] == [0.85, 0.65]


def test_history_note_is_empty_without_a_saturation_streak(tmp_path: Path) -> None:
    _register(tmp_path, "m1", 1, {
        "precision": 0.9, "recall": 0.8, "f1": 0.85, "panel_count": 10, "saturated": False,
    })

    history = table_cell_model_history(tmp_path)

    assert history["saturated_streak"] == 0
    assert history["note"] == ""


def test_history_tolerates_models_registered_before_the_sweep_existed(tmp_path: Path) -> None:
    # Older registered models simply lack saturated/strictest_clean_iou_threshold.
    _register(tmp_path, "m1", 1, {"precision": 0.9, "recall": 0.8, "f1": 0.85, "panel_count": 10})

    history = table_cell_model_history(tmp_path)

    assert history["models"][0]["saturated"] is None
    assert history["models"][0]["strictest_clean_iou_threshold"] is None
    assert history["saturated_streak"] == 0
