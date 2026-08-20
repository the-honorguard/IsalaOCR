from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_step1_webui_is_one_click_preparation() -> None:
    source = (
        ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "preparation-page.js"
    ).read_text(encoding="utf-8")

    assert "actionId: '1'" in source
    assert "title: 'Alles voorbereiden'" in source
    assert "repairPlan(" not in source
    assert "preparation-maintenance')?.remove()" in source
    assert "repairActionId.value = ONE_CLICK_PREPARATION.actionId" in source


def test_step1_cli_runs_full_preparation_without_submenu() -> None:
    source = (ROOT / "automation" / "powershell" / "training-menu.ps1").read_text(encoding="utf-8")

    assert '"1"  = @{ Name = "Voorbereiding"; ActionId = "1" }' in source
    assert 'Invoke-IsalaMenuAction -ActionId "1"' in source
    assert 'Read-Host "Kies voorbereidingstaak"' not in source
    assert 'P. Alle downloads parallel' not in source
    assert 'B. Alle installaties/builds' not in source
    assert 'V. Alle installatiechecks' not in source
