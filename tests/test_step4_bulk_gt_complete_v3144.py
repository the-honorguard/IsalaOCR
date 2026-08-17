from pathlib import Path


def test_step4_gt_index_has_bulk_complete_control():
    template = (
        Path(__file__).resolve().parents[1]
        / "application"
        / "src"
        / "isala_ocr"
        / "training"
        / "templates"
        / "detection_review_index.html"
    ).read_text(encoding="utf-8")

    assert 'id="complete-all-gt-sources"' in template
    assert "Alles als klaar markeren" in template
    assert 'data-gt-source-id="{{ source.source_id }}"' in template
    assert 'data-review-completed="{{ 1 if source.review_completed else 0 }}"' in template
    assert "/api/detection-review/${encodeURIComponent(sourceId)}/complete" in template
    assert "JSON.stringify({completed:true})" in template
    assert "De Ground Truth-kaders zelf worden niet aangepast." in template


def test_bulk_complete_control_is_only_shown_for_open_canonical_gt_sources():
    template = (
        Path(__file__).resolve().parents[1]
        / "application"
        / "src"
        / "isala_ocr"
        / "training"
        / "templates"
        / "detection_review_index.html"
    ).read_text(encoding="utf-8")

    assert "{% if gt_mode and open_source_count %}" in template
    assert "{% if open_source_count %}<button type=\"button\" class=\"ghost\" id=\"complete-all-gt-sources\"" in template
