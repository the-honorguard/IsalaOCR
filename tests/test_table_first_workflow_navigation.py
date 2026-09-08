from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates"


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_table_first_sidebar_uses_region_and_cell_chapters():
    base = _template("base.html")
    assert ">VOORBEREIDING<" in base
    assert ">TABELREGIO<" in base
    assert ">CELLEN<" in base
    assert "('detection-models','1','Voorbereiding'" in base
    assert "('input-selection','2','Inputselectie'" in base
    assert "('panel-setup','3','Tabelregio GT'" in base
    assert "('table-region-model','4','Tabelregio trainen'" in base
    assert "('detect-candidates','5','Tabelregio beoordelen'" in base
    assert "('detect-candidates','6','Tabelregio selecteren'" in base
    assert "('detection-review','7','GT Studio'" in base
    assert "('table-model','8','Celdetector trainen'" in base
    assert "('table-compare','9','Celdetector reviewen'" in base
    assert '<span class="process-tab-number">10</span><span>Tabelstudio</span>' in base


def test_region_review_and_semantic_selection_are_separate_views():
    review = _template("table_region_review.html")
    assert "request.args.get('view') == 'panels'" in review
    assert "Stap {{ 6 if panel_mode else 5 }}" in review
    assert "Door naar Stap 6 · tabelregio selecteren" in review
    assert "Deze labels worden downstream gebruikt" in review
    assert 'name="action_id" value="2"' not in review


def test_gt_studio_owns_initial_cell_detection():
    studio = _template("detection_review_index.html")
    assert "Stap 7 · GT Studio" in studio
    assert 'name="action_id" value="2"' in studio
    assert "Eerste / nieuwe celdetectie starten" in studio
    assert "Stap 8 · celdetector trainen" in studio
