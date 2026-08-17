from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_detection_review_selection_never_scrolls_the_document_to_queue_row() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    assert "scrollIntoView" not in template
    assert "keepRowVisibleInCandidateList" in template
    assert "candidateList.scrollTop" in template
    assert "getBoundingClientRect()" in template


def test_candidate_queue_is_its_own_scroll_container() -> None:
    css = (ROOT / "application/src/isala_ocr/training/static/app.css").read_text(encoding="utf-8")
    assert ".detection-candidate-list{overflow:auto" in css
    assert "min-height:0" in css
    assert "overscroll-behavior:contain" in css
