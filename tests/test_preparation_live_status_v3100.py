from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prepare_all_check_continues_after_individual_failures_and_refreshes_snapshot() -> None:
    script = (ROOT / "automation" / "powershell" / "prepare-training-core.ps1").read_text(encoding="utf-8")
    assert "function Invoke-AllChecks" in script
    assert 'Invoke-AllChecks' in script
    assert 'finally {' in script
    assert 'Update-PreparationStatusSnapshot' in script
    assert 'One or more preparation checks failed' in script


def test_preparation_page_has_live_status_client_and_api_contract() -> None:
    template = (ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "process_step.html").read_text(encoding="utf-8")
    client = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "preparation-page.js").read_text(encoding="utf-8")
    webui = (ROOT / "application" / "src" / "isala_ocr" / "training" / "webui.py").read_text(encoding="utf-8")
    # The /api/v2/preparation route lives in routes_localization_v2.py now;
    # preparation_for_current_strategy() itself stayed in webui.py.
    routes_localization_v2 = (
        ROOT / "application" / "src" / "isala_ocr" / "training" / "routes_localization_v2.py"
    ).read_text(encoding="utf-8")
    assert "preparation-page.js" in template
    assert 'data-prep-component="{{ item.key }}"' in template
    assert "/api/v2/preparation" in client
    assert "action_id: '19'" in client
    assert '@app.get("/api/v2/preparation")' in routes_localization_v2
    assert 'snapshot_age_seconds <= 86400.0' in webui
    assert '"status_stale": not status_fresh' in webui
