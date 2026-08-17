from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "automation" / "training_runtime" / "paddledet_compat"
RUNNER = ROOT / "automation" / "training_runtime" / "localization_runner.py"


def test_pkg_resources_compat_redirects_relative_bbox_json(tmp_path: Path) -> None:
    cwd = tmp_path / "source_checkout"
    target = tmp_path / "run" / "evaluation_artifacts"
    cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(COMPAT)
    env["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(target)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import pkg_resources, json; "
            "open('bbox.json','w').write('{\"ok\": true}'); "
            "assert json.load(open('bbox.json'))['ok'] is True",
        ],
        cwd=cwd,
        env=env,
        check=True,
    )
    assert not (cwd / "bbox.json").exists()
    assert (target / "bbox.json").is_file()


def test_pkg_resources_compat_does_not_redirect_unrelated_files(tmp_path: Path) -> None:
    cwd = tmp_path / "source_checkout"
    target = tmp_path / "run" / "evaluation_artifacts"
    cwd.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(COMPAT)
    env["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(target)
    subprocess.run(
        [sys.executable, "-c", "import pkg_resources; open('normal.json','w').write('{}')"],
        cwd=cwd,
        env=env,
        check=True,
    )
    assert (cwd / "normal.json").is_file()
    assert not (target / "normal.json").exists()


def test_localization_runner_binds_eval_artifact_directory_to_train_run() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    assert 'eval_artifact_dir = output / "evaluation_artifacts"' in source
    assert 'environment["ISALA_PADDLEDET_EVAL_ARTIFACT_DIR"] = str(eval_artifact_dir)' in source
    assert "eval_artifact_dir=eval_artifact_dir" in source
