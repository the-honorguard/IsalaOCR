from pathlib import Path

from isala_ocr.training.localization_dataset import _detection_match_details


ROOT = Path(__file__).resolve().parents[1]


def _ann(box, *, role="positive", annotation_id="ann"):
    x1, y1, x2, y2 = box
    return {
        "annotation_id": annotation_id,
        "training_role": role,
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
    }


def _pred(box, score=0.9):
    return {"coordinate": list(box), "score": score}


def test_match_details_exposes_tp_fp_fn_and_actionable_fp_causes():
    truths = [
        _ann((10, 10, 30, 30), annotation_id="truth-1"),
        _ann((50, 10, 70, 30), annotation_id="truth-2"),
    ]
    negatives = [_ann((80, 10, 100, 30), role="negative", annotation_id="negative-1")]
    predictions = [
        _pred((10, 10, 30, 30), 0.99),       # TP truth-1
        _pred((11, 10, 31, 30), 0.90),       # duplicate truth-1
        _pred((46, 10, 65, 30), 0.85),       # near truth-2, IoU below .75
        _pred((82, 10, 98, 30), 0.80),       # explicit negative region
        _pred((120, 60, 140, 80), 0.75),     # unmatched
    ]

    result = _detection_match_details(
        predictions, truths, negatives, minimum_confidence=0.25, iou_threshold=0.75
    )

    assert len(result["true_positives"]) == 1
    assert len(result["false_positives"]) == 4
    assert len(result["false_negatives"]) == 1
    assert {item["cause"] for item in result["false_positives"]} == {
        "duplicate", "localization", "negative_region", "unmatched"
    }
    assert result["cause_counts"] == {
        "duplicate": 1,
        "localization": 1,
        "negative_region": 1,
        "unmatched": 1,
    }
    assert result["true_positives"][0]["truth_annotation_id"] == "truth-1"
    assert result["false_negatives"][0]["truth_annotation_id"] == "truth-2"


def test_visual_diagnostics_are_wired_into_step5_and_can_confirm_missing_ground_truth():
    # api_v2_localization_quality_details() lives in routes_localization_v2.py now.
    webui = (ROOT / "application/src/isala_ocr/training/routes_localization_v2.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    css = (ROOT / "application/src/isala_ocr/training/static/react/localization-quality.css").read_text(encoding="utf-8")

    assert '/api/v2/localization/quality/details' in webui
    assert "localization_evaluation_details" in webui
    assert "Waarom faalt de detector?" in frontend
    assert "Alleen rood (FP)" in frontend
    assert "Alleen oranje (FN)" in frontend
    assert "voeg toe aan ground truth" in frontend
    assert "/api/detection-review/" in frontend
    assert "diagnostic-overlay" in css
    assert "diagnostic-box.fp" in css
    assert "diagnostic-box.fn" in css


def test_threshold_sweep_reaches_high_confidence_for_fp_calibration():
    expected = "0.50,0.60,0.70,0.80,0.90,0.95"
    assert expected in (ROOT / "automation/powershell/evaluate-localization.ps1").read_text(encoding="utf-8")
    assert expected in (ROOT / "automation/powershell/train-localization-model.ps1").read_text(encoding="utf-8")
    assert expected in (ROOT / "application/src/isala_ocr/cli.py").read_text(encoding="utf-8")


def test_visual_diagnostics_api_uses_saved_predictions_without_retraining(tmp_path: Path):
    import json
    import pytest

    pytest.importorskip("flask")
    from isala_ocr.training.db import TrainingDatabase
    from isala_ocr.training.webui import create_web_app

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.10.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(
        base,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project_root,
    )
    workspace = base / "projects" / "cmr_testcase_01"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source_id = "visual-source"
    db.replace_localization_detection({
        "source_id": source_id,
        "image_width": 200,
        "image_height": 100,
        "render_path": f"source_renders/{source_id}.png",
        "detector_version": "test",
        "token_count": 0,
    }, [])
    db.add_detection_annotation(source_id=source_id, box=(10, 10, 30, 30), reason_code="other")
    db.add_detection_annotation(source_id=source_id, box=(50, 10, 70, 30), reason_code="other")

    dataset_id = "loc-visual"
    dataset_root = workspace / "localization_datasets" / dataset_id
    dataset_root.mkdir(parents=True)
    (dataset_root / "manifest.json").write_text(json.dumps({
        "dataset_id": dataset_id,
        "source_splits": {source_id: "test"},
    }), encoding="utf-8")
    (dataset_root / "images").mkdir(parents=True)
    (dataset_root / "images" / f"{source_id}.png").write_bytes(b"test")
    (dataset_root / "annotations").mkdir(parents=True)
    (dataset_root / "annotations" / "instance_test.json").write_text(json.dumps({
        "images": [{"id": 1, "file_name": f"{source_id}.png", "width": 200, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0, "ignore": 0},
            {"id": 2, "image_id": 1, "category_id": 1, "bbox": [50, 10, 20, 20], "area": 400, "iscrowd": 0, "ignore": 0},
        ],
        "categories": [{"id": 1, "name": "field_roi", "supercategory": "field"}],
    }), encoding="utf-8")
    (workspace / "localization_datasets" / "latest.txt").write_text(dataset_id, encoding="ascii")

    pred_rel = Path("localization_diagnostics") / "visual-predictions.json"
    pred_path = workspace / pred_rel
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    pred_path.write_text(json.dumps({
        "threshold": 0.01,
        "predictions": {
            source_id: [
                {"coordinate": [10, 10, 30, 30], "score": 0.95},
                {"coordinate": [120, 40, 140, 60], "score": 0.80},
            ]
        },
    }), encoding="utf-8")
    db.save_localization_evaluation({
        "evaluation_id": "eval-visual",
        "model_id": "field-visual",
        "dataset_id": dataset_id,
        "kind": "trained",
        "split": "test",
        "metrics": {"minimum_confidence": 0.25, "iou_threshold": 0.75},
        "predictions_path": pred_rel.as_posix(),
        "created_at": "2026-08-12T12:00:00+00:00",
    })

    response = app.test_client().get(
        "/api/v2/localization/quality/details?evaluation_id=eval-visual&threshold=0.25&split=test"
    )
    assert response.status_code == 200
    detail = response.get_json()["details"]
    assert detail["summary"]["true_positives"] == 1
    assert detail["summary"]["false_positives"] == 1
    assert detail["summary"]["false_negatives"] == 1
    assert detail["sources"][0]["false_positives"][0]["cause"] == "unmatched"
