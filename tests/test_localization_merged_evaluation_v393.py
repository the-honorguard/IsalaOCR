from __future__ import annotations

from pathlib import Path


def test_step5_is_merged_evaluate_compare_and_step6_is_activation() -> None:
    root = Path(__file__).resolve().parents[1]
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    menu = (root / "automation/powershell/training-menu.ps1").read_text(encoding="utf-8")
    evaluate = (root / "automation/powershell/evaluate-localization.ps1").read_text(encoding="utf-8")
    assert '"key": "localization-evaluate","index":None,"group":"fallback"' in webui
    assert '"title":"Box-detector evalueren"' in webui
    assert '"key": "localization-register","index":None,"group":"fallback"' in webui
    assert '"localization-compare": "localization-evaluate"' in webui
    assert '"F2" = @{ Name = "Fallback · box-detector evalueren"' in menu
    assert "compare-localization --workspace" in evaluate
    assert "localization_artifact_selection.json" in evaluate
    assert "--dataset-id $DatasetId" in evaluate


def test_quality_page_has_no_permanent_loading_failure_from_react18_only_mount() -> None:
    root = Path(__file__).resolve().parents[1]
    built = (root / "application/src/isala_ocr/training/static/react/localization-quality.js").read_text(encoding="utf-8")
    vendor = (root / "application/src/isala_ocr/training/static/react-vendor/react-dom.production.min.js").read_text(encoding="utf-8", errors="ignore")
    assert "React v16.0.1" in vendor[:300]
    assert "ReactDOM.render" in built
    assert "ReactDOM.createRoot" not in built
    assert "React.Fragment" not in built
