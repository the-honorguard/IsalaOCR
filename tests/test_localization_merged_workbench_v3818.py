from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_paddlex_validation_marker_is_read_by_training_preflight() -> None:
    preflight = (ROOT / "automation/powershell/preflight.ps1").read_text(encoding="utf-8")
    runner = (ROOT / "automation/training_runtime/localization_runner.py").read_text(encoding="utf-8")
    assert '([string]$paddlexValidation.status -eq "ok")' in preflight
    assert '$paddlexValidation.ok' in preflight
    assert '"status": "ok", "ok": True' in runner


def test_step_four_contains_build_validate_and_train_controls() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")
    assert "1 · Dataset bouwen" in template
    assert "2 · Dataset valideren" in template
    assert "3 · GPU trainen" in template
    assert "PaddleX" in template
    assert "Split actueel" in template
    assert "KLAAR" in template


def test_old_localization_process_urls_redirect_to_step_four(tmp_path: Path) -> None:
    pytest.importorskip("flask")
    import sys
    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import create_web_app

    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.8.18", encoding="utf-8")
    app = create_web_app(
        tmp_path / "training" / "workspace",
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    client = app.test_client()
    for old in ("localization-validate", "localization-train"):
        response = client.get(f"/process/{old}")
        assert response.status_code in {301, 302, 303, 307, 308}
        assert response.headers["Location"].endswith("/process/localization-dataset")
