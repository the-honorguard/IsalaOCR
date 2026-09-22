"""The proefpagina list's "Testen"/"Opnieuw proberen" buttons queue a rerun
via ``fetch`` instead of a full form submission (see test_pipeline.html), so
clicking one never navigates the page away and the user can queue several
reruns back to back without waiting on each one to actually start. The
``/test-pipeline/opnieuw-testen/<source_id>`` route tells the two call styles
apart by the ``X-Test-Pipeline-Async`` header the JS sends: with it, the
route answers with JSON instead of a redirect; without it (a JS-disabled
plain form submit), the original redirect behaviour is unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.webui import create_web_app


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    return app


def test_async_header_returns_json_instead_of_redirecting(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = app.test_client().post(
        "/test-pipeline/opnieuw-testen/does-not-exist",
        headers={"X-Test-Pipeline-Async": "1"},
    )
    assert response.status_code == 400, "no matching input file -- must fail, not silently succeed"
    data = response.get_json()
    assert data["ok"] is False
    assert data["error"] == "not_found"
    assert data["message"]


def test_plain_form_submission_still_redirects(tmp_path: Path) -> None:
    app = _app(tmp_path)
    response = app.test_client().post("/test-pipeline/opnieuw-testen/does-not-exist")
    assert response.status_code == 302, "a JS-disabled fallback must keep working via the classic redirect"
    assert "rerun_error=not_found" in response.headers["Location"]
