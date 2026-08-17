from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _template() -> str:
    return (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")


def test_fast_review_is_exception_first_with_default_include() -> None:
    template = _template()
    assert 'id="default-include" checked' in template
    assert "Rest standaard includeren" in template
    assert 'id="dock-include"' in template
    assert 'id="dock-irrelevant"' in template
    assert 'id="dock-reject"' in template
    assert 'id="dock-reject-reason"' in template
    assert 'id="source-done"' in template
    # Reasons belong to incorrect detection, not to relevance classification.
    assert 'id="relevance-reason"' not in template
    assert "quick-scope" not in template


def test_fast_review_supports_keyboard_decisions_and_navigation() -> None:
    template = _template()
    assert "e.key==='c'||e.key==='C'" in template
    assert "e.key==='n'||e.key==='N'" in template
    assert "e.key==='x'||e.key==='X'" in template
    assert "e.key==='e'||e.key==='E'" in template
    assert "selectNextPending()" in template
    assert "function nextSource()" in template
