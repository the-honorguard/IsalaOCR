from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "automation" / "training_runtime" / "localization_runner.py"


def _runner():
    spec = importlib.util.spec_from_file_location("isala_localization_runner_v399", RUNNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dataset(tmp_path: Path, image_count: int) -> Path:
    root = tmp_path / "dataset"
    (root / "annotations").mkdir(parents=True)
    (root / "images").mkdir()
    images = []
    annotations = []
    for index in range(image_count):
        images.append({"id": index + 1, "file_name": f"img-{index}.png", "width": 100, "height": 100})
        annotations.append({"id": index + 1, "image_id": index + 1, "category_id": 1, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0})
        (root / "images" / f"img-{index}.png").write_bytes(b"image")
    payload = {"images": images, "annotations": annotations, "categories": [{"id": 1, "name": "field_roi"}]}
    for split in ("train", "val", "test"):
        (root / "annotations" / f"instance_{split}.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_nine_train_images_use_small_dataset_profile(tmp_path: Path) -> None:
    runner = _runner()
    dataset = _dataset(tmp_path, 9)
    settings = runner.resolve_training_settings(dataset)
    assert settings["profile"] == "small-dataset"
    assert settings["epochs"] == 150
    assert settings["batch_size"] == 2
    assert settings["learning_rate"] == 0.005
    assert settings["warmup_steps"] == 20
    assert settings["eval_interval"] == 5
    assert settings["steps_per_epoch"] == 5
    assert settings["estimated_optimizer_steps"] == 750


def test_explicit_training_overrides_win(tmp_path: Path) -> None:
    runner = _runner()
    dataset = _dataset(tmp_path, 9)
    settings = runner.resolve_training_settings(
        dataset, epochs=25, batch_size=3, learning_rate=0.001, warmup_steps=4, eval_interval=2
    )
    assert settings["epochs"] == 25
    assert settings["batch_size"] == 3
    assert settings["learning_rate"] == 0.001
    assert settings["warmup_steps"] == 4
    assert settings["eval_interval"] == 2
    assert settings["steps_per_epoch"] == 3
    assert settings["estimated_optimizer_steps"] == 75


def test_sanity_prediction_check_detects_live_inference(tmp_path: Path) -> None:
    runner = _runner()
    dataset = _dataset(tmp_path, 1)
    predictions = tmp_path / "predictions.json"
    predictions.write_text(json.dumps({
        "predictions": {
            "img-0": [{"score": 0.9, "coordinate": [10, 10, 30, 30], "bbox_format": "xyxy"}]
        }
    }), encoding="utf-8")
    result = runner.evaluate_sanity_predictions(dataset, predictions)
    assert result["passed"] is True
    assert result["predictions"] == 1
    assert result["true_positives"] == 1
    assert result["recall_at_iou_0_50"] == 1.0


def test_training_launcher_runs_sanity_before_full_training() -> None:
    text = (ROOT / "automation" / "powershell" / "train-localization-model.ps1").read_text(encoding="utf-8")
    assert "[int]$Epochs = 0" in text
    sanity = text.index("localization_runner.py sanity-check")
    full = text.index('"/opt/isala-training/localization_runner.py", "train"')
    assert sanity < full
    assert "Full training was not started" in text


def test_runner_persists_effective_training_configuration() -> None:
    text = RUNNER_PATH.read_text(encoding="utf-8")
    for required in (
        "Train.batch_size=",
        "Train.learning_rate=",
        "Train.warmup_steps=",
        "Train.eval_interval=",
        'training_config.json',
        'effective_paddledet.yml',
    ):
        assert required in text


def test_step4_surfaces_automatic_training_profile() -> None:
    backend = (ROOT / "application" / "src" / "isala_ocr" / "training" / "webui.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend" / "src" / "localization-workbench.ts").read_text(encoding="utf-8")
    assert '"training_profile": training_profile' in backend
    assert 'name": "kleine dataset"' in backend
    assert "sanity_check" in frontend
    assert "Profiel:" in frontend
