from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_runner():
    path = ROOT / "automation" / "training_runtime" / "paddlex_runner.py"
    spec = importlib.util.spec_from_file_location("isala_paddlex_runner_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gpu_image_build_verification_does_not_import_cuda_runtime() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    verify = dockerfile.split("<<'PYVERIFY'", 1)[1].split("PYVERIFY", 1)[0]
    assert "import paddle\n" not in verify
    assert "import paddlex\n" not in verify
    assert 'paddlex_distributions = distribution_versions("paddlex")' in verify
    assert 'paddle_distributions = distribution_versions("paddlepaddle-gpu", "paddlepaddle")' in verify
    assert 'glob("**/libpaddle.so")' in verify
    assert "PaddlePaddle import verification: deferred to container runtime" in verify
    assert "PaddleX authoritative source overlay version" in verify
    assert "Unexpected PaddleX distribution version" not in verify


def test_gpu_runtime_preflight_reports_visible_cuda_device(monkeypatch, capsys) -> None:
    runner = _load_runner()
    fake_paddle = SimpleNamespace(
        __version__="3.3.0",
        is_compiled_with_cuda=lambda: True,
        device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 1)),
    )
    monkeypatch.setitem(sys.modules, "paddle", fake_paddle)

    report = runner._verify_paddle_runtime("gpu:0")

    assert report["version"] == "3.3.0"
    assert report["compiled_with_cuda"] is True
    assert report["cuda_device_count"] == 1
    assert "PaddlePaddle runtime verification" in capsys.readouterr().out


def test_gpu_runtime_preflight_rejects_missing_visible_device(monkeypatch) -> None:
    runner = _load_runner()
    fake_paddle = SimpleNamespace(
        __version__="3.3.0",
        is_compiled_with_cuda=lambda: True,
        device=SimpleNamespace(cuda=SimpleNamespace(device_count=lambda: 0)),
    )
    monkeypatch.setitem(sys.modules, "paddle", fake_paddle)

    with pytest.raises(RuntimeError, match="No CUDA device is visible"):
        runner._verify_paddle_runtime("gpu:0")
