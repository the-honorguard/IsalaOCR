from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = ROOT / "automation" / "powershell"
PREFLIGHT = POWERSHELL / "preflight.ps1"


def _catalog_ids() -> set[str]:
    text = PREFLIGHT.read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"(\d+)"\s*=\s*@\{', text, re.MULTILINE))


def test_web_start_action_is_registered() -> None:
    text = PREFLIGHT.read_text(encoding="utf-8")
    assert re.search(
        r'^\s*"3"\s*=\s*@\{[^\n]*Script\s*=\s*"label-training-data\.ps1"[^\n]*Profile\s*=\s*"webui-start"',
        text,
        re.MULTILINE,
    )
    labeler = (POWERSHELL / "label-training-data.ps1").read_text(encoding="utf-8")
    assert 'Assert-IsalaActionPreflight -ActionId "3"' in labeler


def test_literal_preflight_action_ids_exist_in_catalog() -> None:
    ids = _catalog_ids()
    missing: list[tuple[str, str]] = []
    pattern = re.compile(r'Assert-IsalaActionPreflight\s+-ActionId\s+"(\d+)"')
    for path in POWERSHELL.glob("*.ps1"):
        text = path.read_text(encoding="utf-8")
        for action_id in pattern.findall(text):
            if action_id not in ids:
                missing.append((path.name, action_id))
    assert not missing, f"PowerShell scripts reference unregistered preflight actions: {missing}"


def test_legacy_recognition_scripts_do_not_reuse_new_pipeline_action_ids() -> None:
    expected = {
        "compare-models.ps1": "114",
        "export-recognition-model.ps1": "112",
        "register-recognition-model.ps1": "115",
        "activate-recognition-model.ps1": "116",
    }
    for filename, action_id in expected.items():
        text = (POWERSHELL / filename).read_text(encoding="utf-8")
        assert f'Assert-IsalaActionPreflight -ActionId "{action_id}"' in text


def test_web_utilities_use_web_start_preflight_not_recycled_menu_numbers() -> None:
    for filename in ("stop-label-interface.ps1", "diagnose-label-interface.ps1", "training-status.ps1"):
        text = (POWERSHELL / filename).read_text(encoding="utf-8")
        assert 'Assert-IsalaActionPreflight -ActionId "3"' in text
