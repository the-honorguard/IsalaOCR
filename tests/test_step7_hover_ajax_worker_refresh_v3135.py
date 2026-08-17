from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application/src/isala_ocr/training/templates/table_model_comparison.html"
WEBUI = ROOT / "application/src/isala_ocr/training/webui.py"
APP_JS = ROOT / "application/src/isala_ocr/training/static/app.js"


def test_step7_issue_rows_map_hover_to_exact_overlay_boxes():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert 'data-compare-issue-id="{{ issue.issue_id }}"' in template
    assert 'data-issue-id="{{ issue.issue_id }}"' in template
    assert "pointerenter" in template
    assert "pointerleave" in template
    assert "compare-box.is-hovered" in template
    assert "Beweeg over een afwijking rechts" in template


def test_step7_review_forms_submit_ajax_without_full_page_refresh():
    template = TEMPLATE.read_text(encoding="utf-8")
    webui = WEBUI.read_text(encoding="utf-8")
    assert 'class="comparison-issue-form"' in template
    assert "event.preventDefault();submitIssueForm(form)" in template
    assert "'X-Requested-With':'XMLHttpRequest'" in template
    assert "comparison-inline-status" in template
    assert '"counts": {' in webui
    assert '"decision": effective_decision' in webui
    assert 'request.headers.get("X-Requested-With") == "XMLHttpRequest"' in webui


def test_worker_jobs_refresh_page_after_success_and_restore_scroll():
    js = APP_JS.read_text(encoding="utf-8")
    assert "refreshOnCompleteJobs" in js
    assert "status === 'completed'" in js
    assert "refreshPageAfterCompletedJob(job)" in js
    assert "window.location.replace(window.location.href)" in js
    assert "isala-auto-refresh-scroll" in js
    assert "window.scrollTo({top: y" in js
    assert "form.dataset.refreshOnComplete !== '0'" in js
