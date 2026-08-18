from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates"


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_table_first_sidebar_uses_single_gt_studio_and_seven_step_flow() -> None:
    base = _read("base.html")

    assert "GROUND TRUTH" in base
    assert "MODEL ITERATIE · 4 → 5 → 6 → 7 → 4" in base
    assert '<span class="process-tab-number">3</span><span>GT Studio</span>' in base
    assert '<span class="process-tab-number">4</span><span>Dataset bouwen & valideren</span>' in base
    assert '<span class="process-tab-number">5</span><span>Model trainen & activeren</span>' in base
    assert '<span class="process-tab-number">6</span><span>Nieuwe detectierun</span>' in base
    assert '<span class="process-tab-number">7</span><span>Vervolg-review</span>' in base
    assert '<span class="process-tab-number">3</span><span>Ground Truth maken</span>' not in base
    assert '<span class="process-tab-number">4</span><span>Ground Truth beheren</span>' not in base


def test_gt_studio_contains_detection_proposal_and_persistent_gt_management() -> None:
    template = _read("detection_review_index.html")

    assert "Stap 3 · GT Studio" in template
    assert "GT is de waarheid, detectie is alleen een voorstel" in template
    assert 'href="/process/detect-candidates"' in template
    assert "Detectievoorstel genereren / vernieuwen" in template
    assert "GT controleren" in template
    assert "GT bewerken" in template
    assert 'href="/process/table-quality?stage=dataset"' in template


def test_step4_and_step5_are_separate_views_on_existing_quality_backend() -> None:
    template = _read("table_quality.html")

    assert "Stap 4 · Dataset bouwen & valideren" in template
    assert "Stap 5 · Model trainen & activeren" in template
    assert 'name="action_id" value="48"' in template
    assert 'name="action_id" value="49"' in template
    assert 'name="action_id" value="50"' in template
    assert 'name="action_id" value="51"' in template
    assert 'name="action_id" value="52"' in template
    assert "Stap 5 traint en activeert alleen" in template
    assert "geen nieuwe detectierun gestart" in template


def test_step6_runs_active_model_and_preserves_gt_separation() -> None:
    template = _read("table_model_training.html")

    assert "Stap 6 · Nieuwe detectierun + modelvergelijking" in template
    assert "Actief model opnieuw draaien" in template
    assert 'name="action_id" value="2"' in template
    assert 'name="table_model_id" value="{{ active_model.model_id }}"' in template
    assert "Run ≠ Ground Truth" in template
    assert 'href="/process/table-compare"' in template


def test_step7_is_follow_up_review_without_client_side_renumbering() -> None:
    base = _read("base.html")

    assert "Stap 7 · Vervolg-review" in base
    assert "Stap 7" in base
    assert "replaceAll('Stap 7','Stap 6')" not in base
    assert "window.location.replace('/process/table-compare')" not in base


def test_home_explains_persistent_gt_and_versioned_iteration() -> None:
    home = _read("home.html")

    assert "Stap 3 is de enige plek waar je de waarheid beheert" in home
    assert "4 → 5 → 6 → 7 → 4" in home
    assert "GT Studio" in home
    assert "Dataset bouwen & valideren" in home
    assert "Model trainen & activeren" in home
    assert "Nieuwe detectierun + vergelijking" in home
    assert "Vervolg-review" in home
    assert "GT blijft staan" in home
