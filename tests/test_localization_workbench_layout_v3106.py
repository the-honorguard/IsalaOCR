from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "frontend/src/localization-workbench.ts"
CSS = ROOT / "application/src/isala_ocr/training/static/react/localization-workbench.css"
WORKER = ROOT / "automation/powershell/webui-worker.ps1"


def test_phase_headers_keep_number_column_and_text_column_in_sync() -> None:
    source = CLIENT.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    for number in ("1", "2", "3"):
        assert f'className: "react-phase-number", "aria-hidden": "true" }}, "{number}"' in source
    assert "grid-template-columns:38px minmax(0,1fr)" in css
    assert ".react-phase-heading>div{min-width:0}" in css


def test_training_blocker_is_rendered_once_below_both_train_buttons() -> None:
    source = CLIENT.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")
    assert source.count('className: "action-disabled-reason react-train-reason"') == 1
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert ".react-train-reason{grid-column:1/-1" in css


def test_phase_actions_stay_at_bottom_without_fixed_grid_rows() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".react-phase-card{display:flex;flex-direction:column" in css
    assert ".react-phase-card>.react-action-control:last-child,.react-phase-card>.react-train-actions:last-child{margin-top:auto}" in css
    assert "grid-template-rows:auto minmax(30px,auto) auto" not in css


def test_worker_progress_label_uses_ascii_separator() -> None:
    worker = WORKER.read_text(encoding="utf-8")
    assert 'Docker build - stap {0}/{1}' in worker
    assert 'Docker build · stap {0}/{1}' not in worker
