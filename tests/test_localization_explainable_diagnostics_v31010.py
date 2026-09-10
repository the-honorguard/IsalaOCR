import json
from pathlib import Path

from isala_ocr.training.localization_dataset import localization_evaluation_details


ROOT = Path(__file__).resolve().parents[1]


def _frozen_workspace(tmp_path: Path):
    dataset_id = "loc-iou-diagnostic"
    source_id = "source-a"
    dataset = tmp_path / "localization_datasets" / dataset_id
    (dataset / "images").mkdir(parents=True)
    (dataset / "annotations").mkdir(parents=True)
    (dataset / "images" / f"{source_id}.png").write_bytes(b"image-not-decoded-in-this-test")
    annotation = {
        "images": [{"id": 1, "file_name": f"{source_id}.png", "width": 200, "height": 100}],
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 40, 20], "area": 800, "iscrowd": 0, "ignore": 0}
        ],
        "categories": [{"id": 1, "name": "field_roi", "supercategory": "field"}],
    }
    for split in ("train", "val", "test"):
        (dataset / "annotations" / f"instance_{split}.json").write_text(json.dumps(annotation), encoding="utf-8")
    (tmp_path / "localization_datasets" / "latest.txt").write_text(dataset_id, encoding="ascii")
    predictions = tmp_path / "predictions.json"
    # Overlaps the truth but is deliberately not accurate enough for IoU .75.
    predictions.write_text(json.dumps({
        "threshold": 0.01,
        "predictions": {source_id: [{"coordinate": [6, 8, 45, 31], "score": 0.90}]},
    }), encoding="utf-8")
    return dataset_id, source_id, predictions


def test_visual_details_include_iou_sweep_and_keep_canonical_gate_iou(tmp_path: Path):
    dataset_id, _, predictions = _frozen_workspace(tmp_path)
    details = localization_evaluation_details(
        tmp_path,
        predictions,
        model_id="field-test",
        dataset_id=dataset_id,
        minimum_confidence=0.50,
        iou_threshold=0.50,
        canonical_iou_threshold=0.75,
        split="test",
    )
    assert details["iou_threshold"] == 0.50
    assert details["canonical_iou_threshold"] == 0.75
    sweep = {round(float(row["iou_threshold"]), 2): row for row in details["iou_sweep"]}
    assert 0.50 in sweep and 0.75 in sweep
    assert sweep[0.75]["is_gate_iou"] is True
    assert sweep[0.50]["is_gate_iou"] is False
    assert sweep[0.50]["metrics"]["true_positives"] >= sweep[0.75]["metrics"]["true_positives"]


def test_quality_ui_explains_metrics_uses_validation_for_confidence_and_has_iou_sweep():
    source = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    built = (ROOT / "application/src/isala_ocr/training/static/react/localization-quality.js").read_text(encoding="utf-8")
    # api_v2_localization_quality_details() lives in routes_localization_v2.py now.
    webui = (ROOT / "application/src/isala_ocr/training/routes_localization_v2.py").read_text(encoding="utf-8")
    for text in (
        "Wat betekenen deze waarden?",
        "Confidence wordt uitsluitend op VALIDATION gekozen",
        "IoU (alleen diagnose)",
        "Near-match / IoU",
        "echte fout, near-match, duplicate, negatieve regio of ontbrekende annotation",
        "TEST is alleen de hold-out eindmeting",
    ):
        assert text in source
        assert text in built
    assert 'request.args.get("iou")' in webui
    assert "Beste test-threshold" not in source


def test_diagnostic_payload_marks_validation_as_calibration_source():
    source = (ROOT / "application/src/isala_ocr/training/localization_dataset.py").read_text(encoding="utf-8")
    assert '"recommended_source_split": "val" if validation_rows else None' in source
    assert '"production_threshold"' in source
    assert '"production_ready"' in source
    assert "production confidence must come from validation, never from test" in source
