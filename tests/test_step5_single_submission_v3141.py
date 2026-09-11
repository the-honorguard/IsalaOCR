from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_generic_job_handler_still_exists_for_normal_action_forms() -> None:
    script = _text("application/src/isala_ocr/training/static/app.js")
    assert 'document.querySelectorAll(\'form[action="/jobs"]\')' in script
    assert "submitJob(form);" in script
