from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "automation" / "training_runtime"


def test_localization_runner_exports_runtime_directory_to_nested_paddlex():
    text = (RUNTIME / "localization_runner.py").read_text(encoding="utf-8")
    assert "def paddlex_subprocess_environment" in text
    assert 'environment["PYTHONPATH"]' in text
    assert "env=paddlex_subprocess_environment()" in text


def test_pkg_resources_compatibility_is_conditional_and_supports_resource_filename(tmp_path):
    package = tmp_path / "fake_review_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "MODEL_ZOO").write_text("field_roi\n", encoding="utf-8")

    spec = importlib.util.spec_from_file_location(
        "isala_pkg_resources_compat_test",
        RUNTIME / "paddledet_compat" / "pkg_resources.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    sys.path.insert(0, str(tmp_path))
    try:
        resolved = module.resource_filename("fake_review_pkg", "MODEL_ZOO")
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("fake_review_pkg", None)
    assert Path(resolved).read_text(encoding="utf-8") == "field_roi\n"


def test_child_python_imports_local_pkg_resources_compatibility_via_pythonpath():
    # This matches localization_runner: the runtime directory is explicitly
    # prepended to PYTHONPATH for nested PaddleX/PaddleDetection processes.
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(RUNTIME / "paddledet_compat"), str(RUNTIME)])
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import pkg_resources; print(getattr(pkg_resources, '__isala_compat__', False)); "
            "print(hasattr(pkg_resources, 'resource_filename'))",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert lines[-1] == "True"


def test_step4_has_live_readiness_api_and_component_polling():
    client = (ROOT / "frontend" / "src" / "localization-workbench.ts").read_text(encoding="utf-8")
    # This route lives in routes_localization_v2.py now (split out of webui.py).
    webui = (ROOT / "application" / "src" / "isala_ocr" / "training" / "routes_localization_v2.py").read_text(encoding="utf-8")
    app_js = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.js").read_text(encoding="utf-8")
    assert "/api/localization-readiness" in webui
    assert "/api/v2/localization/workbench" in client
    assert "window.setTimeout(() => this.refresh(false), delay)" in client
    assert "active ? 2500 : 12000" in client
    assert "NVIDIA GPU trainen" in client
    assert "window.location.reload" not in client
    assert "isala:job-status" in app_js
    assert "isala:job-created" in app_js
