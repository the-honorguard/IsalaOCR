import json
from pathlib import Path

import pytest

from isala_ocr.training.table_region_training import activate_table_region_model


def _write_run(root: Path, run_id: str, *, inference_dir: str, passed: bool = True, mtime: float | None = None) -> Path:
    run_dir = root / "table_region_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    model = {
        "inference_dir": inference_dir,
        "device": "gpu",
        "dataset_id": "table-regions-abc123",
        "active": False,
        "model_id": f"table-region-{run_id}",
        "run_id": run_id,
    }
    (run_dir / "model.json").write_text(json.dumps(model), encoding="utf-8")
    evaluation_dir = run_dir / "evaluation_artifacts"
    evaluation_dir.mkdir()
    evaluation = {
        "threshold": 0.25,
        "ground_truth": 10,
        "predictions": 10,
        "true_positives": 10,
        "recall_at_iou_0_50": 1.0 if passed else 0.2,
        "precision_at_iou_0_50": 1.0 if passed else 0.2,
        "negative_images": 0,
        "passed": passed,
        "split": "test",
        "status": "completed",
    }
    (evaluation_dir / "test_evaluation.json").write_text(json.dumps(evaluation), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(run_dir, (mtime, mtime))
    return run_dir


def test_activate_table_region_model_translates_absolute_inference_dir(tmp_path: Path) -> None:
    inference_dir = tmp_path / "table_region_runs" / "run-1" / "best_model" / "inference"
    inference_dir.mkdir(parents=True)
    _write_run(tmp_path, "run-1", inference_dir=str(inference_dir))

    active = activate_table_region_model(tmp_path)

    assert active["active"] is True
    assert active["inference_dir"] == "table_region_runs/run-1/best_model/inference"
    assert active["test_evaluation"]["passed"] is True
    # test_evaluation must be appended after the existing model.json keys, matching
    # the key order the previous raw-PowerShell script produced via ConvertTo-Json.
    assert list(active.keys())[-1] == "test_evaluation"

    on_disk = json.loads((tmp_path / "table_region_models" / "active.json").read_text(encoding="utf-8"))
    assert on_disk == active


def test_activate_table_region_model_keeps_relative_inference_dir_as_is(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-1", inference_dir="table_region_runs/run-1/best_model/inference")

    active = activate_table_region_model(tmp_path)

    assert active["inference_dir"] == "table_region_runs/run-1/best_model/inference"


def test_activate_table_region_model_picks_most_recently_modified_run(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-old", inference_dir="table_region_runs/run-old/best_model/inference", mtime=1_000_000)
    _write_run(tmp_path, "run-new", inference_dir="table_region_runs/run-new/best_model/inference", mtime=2_000_000)

    active = activate_table_region_model(tmp_path)

    assert active["run_id"] == "run-new"


def test_activate_table_region_model_raises_without_any_trained_run(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Geen getraind tabelregio-model gevonden"):
        activate_table_region_model(tmp_path)


def test_activate_table_region_model_raises_without_test_evaluation(tmp_path: Path) -> None:
    run_dir = tmp_path / "table_region_runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "model.json").write_text(
        json.dumps({"inference_dir": "table_region_runs/run-1/best_model/inference", "model_id": "m1", "run_id": "run-1"}),
        encoding="utf-8",
    )

    with pytest.raises(FileNotFoundError, match="onafhankelijke test-evaluatie"):
        activate_table_region_model(tmp_path)


def test_activate_table_region_model_raises_when_evaluation_failed(tmp_path: Path) -> None:
    _write_run(tmp_path, "run-1", inference_dir="table_region_runs/run-1/best_model/inference", passed=False)

    with pytest.raises(ValueError, match="faalt de onafhankelijke tabelregio-test"):
        activate_table_region_model(tmp_path)


def test_activate_table_region_model_raises_for_inference_dir_outside_workspace(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-inference"
    _write_run(tmp_path, "run-1", inference_dir=str(outside))

    with pytest.raises(ValueError, match="buiten de projectworkspace"):
        activate_table_region_model(tmp_path)
