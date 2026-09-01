from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_paddledetection_install_skips_only_external_deps_during_build() -> None:
    dockerfile = (ROOT / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    assert "PADDLE_PDX_SKIP_EXTERNAL_DEPS" in dockerfile
    assert 'PADDLE_PDX_SKIP_EXTERNAL_DEPS=1 PYTHONPATH=/opt/paddlex-source' in dockerfile
    assert "paddlex --install PaddleDetection" in dockerfile
    assert "--deps_to_replace PaddleDetection.sklearn=None" in dockerfile
    patch = dockerfile.split("<<'PYPDXPATCH'", 1)[1].split("PYPDXPATCH", 1)[0]
    assert 'PADDLE_PDX_SKIP_EXTERNAL_DEPS' in patch
    assert 'text.find("    import paddle\\n", start)' in patch


def test_action17_runs_gpu_runtime_validation_after_build() -> None:
    core = (ROOT / "automation" / "powershell" / "prepare-training-core.ps1").read_text(encoding="utf-8")
    compose = (ROOT / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert "trainer-gpu-detection" in core
    assert "runtime-check --device gpu:0 --require-paddledet" in core
    assert "gpus: all" in compose


def test_paddlex_runtime_check_can_require_paddledet() -> None:
    runner = (ROOT / "automation" / "training_runtime" / "paddlex_runner.py").read_text(encoding="utf-8")
    assert '"--require-paddledet"' in runner
    assert "import ppdet" in runner
    assert 'importlib.metadata.version("paddledet")' in runner


def test_heavy_training_image_version_remains_reusable() -> None:
    assert (ROOT / "project" / "TRAINING_IMAGE_VERSION").read_text(encoding="utf-8").strip() == "3.8.5"
