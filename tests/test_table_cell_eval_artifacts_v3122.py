from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "automation" / "training_runtime" / "table_cell_runner.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("isala_table_cell_runner_test", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_table_cell_training_sets_writable_paddledet_eval_artifact_dir(tmp_path: Path) -> None:
    runner = _load_runner()
    target = tmp_path / "run" / "evaluation_artifacts"
    environment = runner.env(eval_artifact_dir=target)
    assert environment["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] == str(target.resolve())
    assert target.is_dir()
    assert str(ROOT / "automation" / "training_runtime" / "paddledet_compat") in environment["PYTHONPATH"]


def test_table_cell_training_clears_inherited_eval_artifact_redirect_without_target(monkeypatch) -> None:
    runner = _load_runner()
    monkeypatch.setenv("ISALA_PADDLEDET_EVAL_ARTIFACT_DIR", "/tmp/stale")
    environment = runner.env()
    assert "ISALA_PADDLEDET_EVAL_ARTIFACT_DIR" not in environment


def test_table_cell_train_routes_inline_validation_artifacts_to_run_directory() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert 'eval_artifact_dir=output / "evaluation_artifacts"' in source
    assert 'result["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(eval_artifact_dir)' in source
