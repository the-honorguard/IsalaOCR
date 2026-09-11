from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates"


def test_table_first_sidebar_is_now_a_two_step_iteration_loop() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "MODEL ITERATIE · 5 → 6 → 5" in base
    assert "<span class=\"process-tab-number\">5</span><span>Model trainen & draaien</span>" in base
    assert "<span class=\"process-tab-number\">6</span><span>Afwijkingen reviewen</span>" in base
    assert '<a href="/process/table-model"' not in base
    assert "setTopbar('Stap 6 · Afwijkingen reviewen'" in base


def test_legacy_table_model_page_redirects_to_review() -> None:
    legacy = (TEMPLATES / "table_model_training.html").read_text(encoding="utf-8")

    assert 'content="0;url=/process/table-compare"' in legacy
    assert "window.location.replace('/process/table-compare')" in legacy
    assert "Deze tussenstap bestaat niet meer" in legacy
