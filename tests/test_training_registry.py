import json
from pathlib import Path

import pytest

from isala_ocr.training.registry import activate_model, register_model


def _fake_export(run: Path) -> Path:
    inference = run / "best_accuracy" / "inference"
    inference.mkdir(parents=True)
    (inference / "inference.json").write_text("{}", encoding="utf-8")
    (inference / "inference.pdiparams").write_bytes(b"weights")
    return inference


def test_register_and_activate_model_with_threshold(tmp_path: Path):
    run = tmp_path / "run"
    _fake_export(run)
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(
        json.dumps(
            {
                "dataset_id": "dataset-1",
                "metrics": {"exact_match_accuracy": 0.97, "character_error_rate": 0.01},
            }
        ),
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    manifest = register_model(registry, run, evaluation, model_id="model-1")
    assert manifest["model_id"] == "model-1"

    model_root = tmp_path / "models"
    active = activate_model(registry, model_root, "model-1", minimum_exact_match=0.95)
    assert active["model_id"] == "model-1"
    assert (model_root / "active-recognition" / "inference.json").is_file()
    assert (model_root / "active-recognition" / "isala_model.json").is_file()


def test_activation_blocks_model_below_threshold(tmp_path: Path):
    registry = tmp_path / "registry"
    source = registry / "models" / "low"
    inference = source / "inference"
    inference.mkdir(parents=True)
    (inference / "inference.json").write_text("{}", encoding="utf-8")
    (inference / "inference.pdiparams").write_bytes(b"weights")
    (source / "model.json").write_text(
        json.dumps({"model_id": "low", "metrics": {"exact_match_accuracy": 0.5}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        activate_model(registry, tmp_path / "models", "low", minimum_exact_match=0.9)
