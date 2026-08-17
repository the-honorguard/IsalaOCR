from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "automation" / "training_runtime"


def test_numpy_pickle_compatibility_alias_loads_numpy2_global_with_numpy1_layout(tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    (fake / "numpy" / "core").mkdir(parents=True)
    (fake / "numpy" / "__init__.py").write_text(
        '__version__ = "1.26.4"\nfrom . import core\n', encoding="utf-8"
    )
    (fake / "numpy" / "core" / "__init__.py").write_text("", encoding="utf-8")
    (fake / "numpy" / "core" / "multiarray.py").write_text(
        "def _reconstruct():\n    return 'ok'\n", encoding="utf-8"
    )

    code = (
        "import pickle; "
        "value = pickle.loads(b'cnumpy._core.multiarray\\n_reconstruct\\n.'); "
        "assert callable(value); print(value.__module__)"
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(RUNTIME), str(fake)))
    completed = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    # -S intentionally suppresses sitecustomize. Import it explicitly to keep
    # the test isolated from the host interpreter's normal site configuration.
    explicit = subprocess.run(
        [sys.executable, "-S", "-c", "import sitecustomize; " + code],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert explicit.returncode == 0, explicit.stderr
    assert "numpy.core.multiarray" in explicit.stdout


def test_training_runner_propagates_runtime_sitecustomize_to_paddlex_children() -> None:
    runner = (RUNTIME / "paddlex_runner.py").read_text(encoding="utf-8")
    bootstrap = (RUNTIME / "paddlex_bootstrap.py").read_text(encoding="utf-8")
    assert "def _verify_numpy_pickle_runtime" in runner
    assert 'importlib.import_module("numpy._core.multiarray")' in runner
    assert 'environment["PYTHONPATH"]' in runner
    assert 'subprocess.run(command, check=True, env=environment)' in runner
    assert 'os.environ["PYTHONPATH"]' in bootstrap
    assert "install_numpy_pickle_compatibility()" in bootstrap
