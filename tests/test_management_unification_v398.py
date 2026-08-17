from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_sidebar_has_one_project_model_management_entry() -> None:
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    assert 'href="/manage"' in base
    assert "Projecten & modellen" in base
    assert 'href="/projects" class="project-manage-link"' not in base
    assert "step.group == 'system' and step.key != 'artifacts'" in base


def test_management_template_contains_both_sections() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/management.html").read_text(encoding="utf-8")
    assert 'data-management-tab="projects"' in template
    assert 'data-management-tab="models"' in template
    assert "Nieuw project" in template
    assert 'id="react-localization-artifacts"' in template
    assert "window.location.reload" not in template


try:
    import flask  # noqa: F401
except ModuleNotFoundError:
    FLASK_AVAILABLE = False
    create_web_app = None
else:
    FLASK_AVAILABLE = True
    sys.path.insert(0, str(ROOT / "application" / "src"))
    from isala_ocr.training.webui import create_web_app


@pytest.mark.skipif(not FLASK_AVAILABLE, reason="Flask is not installed in the test runtime")
def test_management_and_legacy_routes_render_combined_page(tmp_path: Path) -> None:
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.9.8", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    client = app.test_client()

    response = client.get("/manage")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Projecten &amp; modellen" in html
    assert "Nieuw project" in html
    assert 'id="react-localization-artifacts"' in html

    projects = client.get("/projects")
    assert projects.status_code == 200
    assert "Nieuw project" in projects.get_data(as_text=True)

    artifacts = client.get("/process/artifacts")
    assert artifacts.status_code == 200
    assert "Data &amp; modellen" in artifacts.get_data(as_text=True)
