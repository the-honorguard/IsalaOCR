from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.training.localization_dataset import diagnose_prediction_file
from test_localization_quality_diagnostics_v391 import THRESHOLDS, _prepare_workspace


ROOT = Path(__file__).resolve().parents[1]


def test_diagnostic_threshold_is_chosen_from_validation_not_test(tmp_path: Path) -> None:
    workspace, manifest, predictions = _prepare_workspace(tmp_path)
    path = workspace / "predictions.json"
    path.write_text(json.dumps({"threshold": 0.01, "predictions": predictions}), encoding="utf-8")

    diagnostic = diagnose_prediction_file(
        workspace,
        path,
        model_id="field-smart-pipeline",
        dataset_id=manifest["dataset_id"],
        confidence_thresholds=[0.01, 0.10, 0.25],
        thresholds=THRESHOLDS,
    )

    assert diagnostic["recommended_source_split"] == "val"
    assert diagnostic["recommended_threshold"] in {0.01, 0.10}
    assert diagnostic["production_threshold"] == 0.10
    pipeline = diagnostic["improvement_pipeline"]
    assert pipeline["calibration"]["source_split"] == "val"
    assert pipeline["calibration"]["production_ready"] is True
    assert [stage["id"] for stage in pipeline["stages"]] == [
        "train_sanity", "validation_calibration", "error_analysis", "final_test"
    ]


def test_quality_ui_is_next_action_first_and_hides_raw_metrics_under_advanced() -> None:
    frontend = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    assert "MODEL IMPROVEMENT ASSISTANT" in frontend
    assert "AANBEVOLEN VOLGENDE STAP" in frontend
    assert "Geavanceerde diagnostiek en ruwe metrics" in frontend
    assert "Confidence wordt uitsluitend op VALIDATION gekozen" in frontend
    assert "TEST is geen tuning-set" in frontend
    assert "Wat betekenen deze waarden?" in frontend


def test_visual_diagnostics_support_split_iou_and_fp_cause_focus() -> None:
    frontend = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert '"IoU (alleen diagnose)"' in frontend
    assert '"TEST (hold-out)"' in frontend
    assert 'Near-match / IoU' in frontend
    assert 'Unmatched' in frontend
    assert 'request.args.get("iou_threshold")' in webui


def test_training_and_step5_keep_test_out_of_threshold_tuning() -> None:
    train_script = (ROOT / "automation/powershell/train-localization-model.ps1").read_text(encoding="utf-8")
    eval_script = (ROOT / "automation/powershell/evaluate-localization.ps1").read_text(encoding="utf-8")
    cli = (ROOT / "application/src/isala_ocr/cli.py").read_text(encoding="utf-8")
    assert "--splits train,val" in train_script
    assert "hold-out TEST split is intentionally not used during training iteration" in train_script
    assert "--splits train,val" in eval_script
    assert "$Selection.evaluation_model_id" in eval_script
    assert "isala_model_registration.json" in eval_script
    assert "HOLD-OUT TEST SKIPPED" in eval_script
    assert "--split test --minimum-confidence $ProductionThreshold" in eval_script
    assert 'loc_diag.add_argument("--splits"' in cli
