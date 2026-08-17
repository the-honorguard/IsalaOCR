from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "job-runtime.js"
TEMPLATE = ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "table_model_comparison.html"


def test_gt_check_saves_before_opening_source_specific_gt_studio() -> None:
    script = STATIC.read_text(encoding="utf-8")
    template = TEMPLATE.read_text(encoding="utf-8")

    assert "row.dataset.issueDecision !== 'gt_check'" in script
    assert "data-issue-decision" in script
    assert "window.location.assign(studioUrl)" in script
    assert 'a[href^="/detection-review/"]' in script

    # Step 7 still records gt_check through its existing AJAX review form first.
    assert 'name="decision" value="gt_check"' in template
    assert 'href="/detection-review/{{ panel.source_id }}"' in template
