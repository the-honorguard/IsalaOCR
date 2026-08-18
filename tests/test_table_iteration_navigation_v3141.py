from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates"


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_table_first_sidebar_separates_gt_setup_from_model_iteration() -> None:
    base = _read("base.html")

    assert "TABLE SETUP & GROUND TRUTH" in base
    assert "MODEL ITERATIE · 5 → 6 → 7 → 5" in base
    assert '<span class="process-tab-number">3</span><span>Ground Truth maken</span>' in base
    assert '<span class="process-tab-number">4</span><span>Ground Truth beheren</span>' in base
    assert '<span class="process-tab-number">5</span><span>Model trainen</span>' in base
    assert '<span class="process-tab-number">6</span><span>Model beoordelen</span>' in base
    assert '<span class="process-tab-number">7</span><span>Afwijkingen reviewen</span>' in base


def test_step5_is_the_single_training_entrypoint() -> None:
    template = _read("table_quality.html")

    assert "Stap 5 · Model trainen" in template
    assert "Nieuwe trainingsronde starten" in template
    assert 'name="action_id" value="53"' in template
    assert "Dataset bouwen → valideren → GPU trainen → activeren" in template
    assert "Train → beoordeel → review → train opnieuw" in template
    assert "Tabeldekking beoordelen" not in template


def test_step6_runs_active_model_without_sending_user_back_to_step3() -> None:
    template = _read("table_model_training.html")

    assert "Stap 6 · Model beoordelen" in template
    assert "Actief model opnieuw draaien" in template
    assert 'name="action_id" value="2"' in template
    assert 'name="table_model_id" value="{{ active.model_id }}"' in template
    assert "Geen terugkoppeling naar Stap 3" in template
    assert "5 → 6 → 7 → 5" in template
    assert 'href="/process/table-compare"' in template


def test_step7_and_step4_links_follow_the_new_iteration_loop() -> None:
    base = _read("base.html")

    assert "Stap 7 · Afwijkingen reviewen" in base
    assert "Stap 5 · Volgende trainingsronde" in base
    assert "Naar Stap 5 · Model trainen →" in base
    assert "link.href='/process/table-quality'" in base
    assert "link.href='/process/table-model'" in base


def test_home_explains_one_time_gt_then_iterative_training() -> None:
    home = _read("home.html")

    assert "Stappen 1–4 bouwen de vaste referentie op" in home
    assert "ITERATIEVE MODELLOOP" in home
    assert "5 → 6 → 7 → 5" in home
    assert "Ground Truth maken" in home
    assert "Model trainen" in home
    assert "Model beoordelen" in home
    assert "Afwijkingen reviewen" in home
