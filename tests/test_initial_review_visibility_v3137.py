from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "application/src/isala_ocr/training/templates/detection_review_index.html"
STUDIO = ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html"
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"


def test_initial_review_source_index_hides_completed_sources_by_default_with_restore_toggle():
    template = INDEX.read_text(encoding="utf-8")
    webui = WEBUI.read_text(encoding="utf-8")
    assert 'id="toggle-completed-sources"' in template
    assert 'data-review-completed="{{ 1 if source.review_completed else 0 }}"' in template
    assert "review-source-complete initial-review-completed hidden" in template
    assert "isala-detection-review:show-completed-sources" in template
    assert "Toon afgeronde reviews" in template
    assert "Verberg afgeronde reviews" in template
    assert "completed_source_count = sum(1 for row in rows" in webui
    assert "open_source_count = max(0, len(rows) - completed_source_count)" in webui


def test_initial_review_open_filter_hides_reviewed_rows_boxes_and_markers_together():
    template = STUDIO.read_text(encoding="utf-8")
    assert 'id="toggle-reviewed-candidates"' in template
    assert "candidateMatchesFilter" in template
    assert "r.classList.toggle('hidden',!show)" in template
    assert "box?.classList.toggle('hidden',!show)" in template
    assert "markerByBox.get(box)?.classList.toggle('hidden',!show)" in template
    assert "Toon beoordeelde" in template
    assert "Beoordeelde verbergen" in template
    assert "isala-detection-review:show-reviewed-candidates" in template


def test_hidden_reviewed_candidates_are_not_marquee_selectable():
    template = STUDIO.read_text(encoding="utf-8")
    assert "boxes.filter(box=>!box.classList.contains('hidden')).filter" in template
    assert "rows.find(r=>r.dataset.status==='pending'&&!r.classList.contains('hidden'))||visibleRows()[0]" in template


def test_source_navigation_skips_completed_initial_review_sources_while_hidden():
    template = STUDIO.read_text(encoding="utf-8")
    webui = WEBUI.read_text(encoding="utf-8")
    assert 'data-review-completed="{{ 1 if item.review_completed else 0 }}"' in template
    assert "const showCompletedSources=gtMode||window.localStorage.getItem('isala-detection-review:show-completed-sources')==='1'" in template
    assert "const navigableSourceQueue=()=>sourceQueue.filter(item=>showCompletedSources||!item.review_completed||item.source_id===currentSourceId)" in template
    assert '"review_completed": bool(item.get("review_completed"))' in webui
