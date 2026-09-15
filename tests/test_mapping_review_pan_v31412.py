from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "application/src/isala_ocr/training/static/mapping-review-studio.js"
VERSION = ROOT / "project/VERSION"


def test_mapping_review_studio_has_explicit_pan_mode():
    js = JS.read_text(encoding="utf-8")

    assert 'id="mapping-review-pan"' in js
    assert "Panmodus aan/uit (P)" in js
    assert "let panMode = false;" in js
    assert "function togglePanMode()" in js
    assert "panButton.addEventListener('click', togglePanMode);" in js
    assert "shouldStart: (event) => (panMode || spaceDown) && event.button === 0," in js
    assert "event.key === 'p' || event.key === 'P'" in js
    assert "viewport.classList.toggle('pan-ready', ready);" in js


def test_space_pan_remains_available_as_temporary_override():
    js = JS.read_text(encoding="utf-8")

    assert "if (event.code === 'Space' && !editing)" in js
    assert "spaceDown = true;" in js
    assert "if (!panMode) endPan();" in js
    assert "syncPanMode();" in js


def test_mapping_review_pan_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.16.0"
