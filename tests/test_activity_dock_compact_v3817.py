from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_activity_terminal_does_not_auto_expand_for_new_jobs() -> None:
    script = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.js").read_text(encoding="utf-8")
    submit = script.split("async function submitJob(form)", 1)[1].split("document.querySelectorAll('form[action=\"/jobs\"]')", 1)[0]
    assert "setExpanded(true)" not in submit
    assert "setActiveJob(payload.job_id, false)" in submit


def test_activity_terminal_uses_new_manual_expansion_preference() -> None:
    script = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.js").read_text(encoding="utf-8")
    assert "isala-activity-terminal-expanded-v2" in script
    initial = script.split("const initiallyExpanded", 1)[1].split(";", 1)[0]
    assert "params.has('job_id')" not in initial
    assert "isala-activity-expanded" not in initial


def test_collapsed_activity_bar_is_compact() -> None:
    css = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "app.css").read_text(encoding="utf-8")
    assert ".activity-dock.collapsed{height:44px}" in css
    assert ".activity-dock.collapsed .activity-worker{display:none}" in css
