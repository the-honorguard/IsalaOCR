from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "roi_review_document.html"


def test_pending_roi_is_preselected_as_correct() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "s.roi_review_status in ['correct','pending']" in text
    assert "standaard op OK" in text
    assert "Alles opslaan als beoordeeld" in text


def test_existing_incorrect_and_pending_options_remain_available() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    assert 'value="incorrect"' in text
    assert 'value="pending"' not in text
    assert 'value="deferred"' in text
    assert "statusLabels={correct:'OK',incorrect:'Fout',deferred:'Later'}" in text
