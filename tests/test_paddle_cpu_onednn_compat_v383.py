from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_localization_runner():
    path = ROOT / "automation" / "training_runtime" / "localization_runner.py"
    spec = importlib.util.spec_from_file_location("isala_localization_runner_v383", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cpu_training_runtime_pins_paddle_322_and_invalidates_old_image() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    compose = (ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")
    environment = (ROOT / "project" / "environment.example").read_text(encoding="utf-8")
    assert "PADDLE_PACKAGE=paddlepaddle==3.2.2" in dockerfile
    assert "PADDLE_CPU_PACKAGE:-paddlepaddle==3.2.2" in compose
    assert "PADDLE_GPU_PACKAGE:-paddlepaddle-gpu==3.2.2" in compose
    assert "PADDLE_CPU_PACKAGE=paddlepaddle==3.2.2" in environment
    assert "PADDLE_GPU_PACKAGE=paddlepaddle-gpu==3.2.2" in environment
    assert (ROOT / "project" / "TRAINING_IMAGE_VERSION").read_text(encoding="utf-8").strip() == "3.8.4"


def test_localization_runner_rejects_known_paddle_33_cpu_regression() -> None:
    runner = _load_localization_runner()
    assert runner._is_unsafe_cpu_paddle_version("3.3.0") is True
    assert runner._is_unsafe_cpu_paddle_version("3.3.1") is True
    assert runner._is_unsafe_cpu_paddle_version("3.2.2") is False
    assert runner._is_unsafe_cpu_paddle_version("3.4.0") is False


def test_prepare_and_cpu_predict_apply_runtime_guard() -> None:
    text = (ROOT / "automation" / "training_runtime" / "localization_runner.py").read_text(encoding="utf-8")
    prepare = text[text.index("def command_prepare"):text.index("\ndef command_check")]
    predict = text[text.index("def command_predict"):text.index("\ndef command_prepare")]
    assert "paddle_version = _verify_cpu_inference_paddle()" in prepare
    assert '"paddle_version": paddle_version' in prepare
    assert 'if device == "cpu":\n        _verify_cpu_inference_paddle()' in predict
    assert "ConvertPirAttribute2RuntimeAttribute" in text
