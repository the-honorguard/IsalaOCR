import builtins
import json
from pathlib import Path

from isala_ocr.training.localization_dataset import (
    localization_dataset_image_path,
    localization_evaluation_details,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_frozen_dataset(root: Path, dataset_id: str = "loc-frozen") -> tuple[str, str]:
    source_id = "visual-source"
    dataset = root / "localization_datasets" / dataset_id
    (dataset / "images").mkdir(parents=True)
    (dataset / "annotations").mkdir(parents=True)
    (dataset / "images" / f"{source_id}.png").write_bytes(b"not-a-real-png-needed-for-path-test")
    (dataset / "manifest.json").write_text(json.dumps({
        "dataset_id": dataset_id,
        "source_splits": {source_id: "test"},
    }), encoding="utf-8")
    (dataset / "annotations" / "instance_test.json").write_text(json.dumps({
        "images": [{"id": 1, "file_name": f"{source_id}.png", "width": 200, "height": 100}],
        "annotations": [
            {"id": 11, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20], "area": 400, "iscrowd": 0, "ignore": 0},
            {"id": 12, "image_id": 1, "category_id": 1, "bbox": [50, 10, 20, 20], "area": 400, "iscrowd": 0, "ignore": 0},
        ],
        "categories": [{"id": 1, "name": "field_roi", "supercategory": "field"}],
    }), encoding="utf-8")
    for split in ("train", "val"):
        (dataset / "annotations" / f"instance_{split}.json").write_text(json.dumps({
            "images": [], "annotations": [],
            "categories": [{"id": 1, "name": "field_roi", "supercategory": "field"}],
        }), encoding="utf-8")
    (root / "localization_datasets" / "latest.txt").write_text(dataset_id, encoding="ascii")
    return dataset_id, source_id


def test_visual_details_use_frozen_coco_ground_truth_and_dataset_image(tmp_path: Path):
    dataset_id, source_id = _write_frozen_dataset(tmp_path)
    predictions = tmp_path / "localization_diagnostics" / "predictions.json"
    predictions.parent.mkdir(parents=True)
    predictions.write_text(json.dumps({
        "threshold": 0.01,
        "predictions": {
            source_id: [
                {"coordinate": [10, 10, 30, 30], "score": 0.95},
                {"coordinate": [120, 40, 140, 60], "score": 0.80},
            ]
        },
    }), encoding="utf-8")

    details = localization_evaluation_details(
        tmp_path,
        predictions,
        model_id="field-visual",
        dataset_id=dataset_id,
        minimum_confidence=0.25,
        iou_threshold=0.75,
        split="test",
    )

    assert details["ground_truth_source"] == "frozen_coco_dataset"
    assert details["summary"]["true_positives"] == 1
    assert details["summary"]["false_positives"] == 1
    assert details["summary"]["false_negatives"] == 1
    assert details["sources"][0]["false_positives"][0]["cause"] == "unmatched"
    assert details["sources"][0]["false_negatives"][0]["truth_annotation_id"] == "coco:12"
    assert localization_dataset_image_path(
        tmp_path, dataset_id=dataset_id, source_id=source_id, split="test"
    ).name == f"{source_id}.png"


def test_threshold_button_always_scrolls_to_diagnostics_and_surfaces_errors():
    frontend = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    assert 'async viewThreshold' in frontend
    assert 'document.getElementById("visual-diagnostics")' in frontend
    assert 'scrollIntoView({ behavior: "smooth", block: "start" })' in frontend
    assert 'this.state.detailError ? hq("div", { className: "notice warning", role: "alert" }' in frontend
    assert 'onClick: () => this.viewThreshold(data, threshold, "val")' in frontend


def test_visual_diagnostics_serve_frozen_dataset_image_and_explain_metric_name():
    # api_v2_localization_quality_image() lives in routes_localization_v2.py now.
    webui = (ROOT / "application/src/isala_ocr/training/routes_localization_v2.py").read_text(encoding="utf-8")
    frontend = (ROOT / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    assert '/api/v2/localization/quality/image/<dataset_id>/<source_id>' in webui
    assert 'localization_dataset_image_path' in webui
    assert 'ground_truth_source": "frozen_coco_dataset"' in (ROOT / "application/src/isala_ocr/training/localization_dataset.py").read_text(encoding="utf-8")
    assert 'Strakke ref.match' in frontend
    assert 'Dit is géén percentage van alle output dat automatisch akkoord is.' in frontend


def test_visual_details_work_when_heavy_localization_module_is_absent(tmp_path: Path, monkeypatch):
    dataset_id, source_id = _write_frozen_dataset(tmp_path, "loc-lightweight-labeler")
    predictions = tmp_path / "localization_diagnostics" / "predictions-lightweight.json"
    predictions.parent.mkdir(parents=True, exist_ok=True)
    predictions.write_text(json.dumps({
        "threshold": 0.01,
        "predictions": {source_id: [{"coordinate": [10, 10, 30, 30], "score": 0.95}]},
    }), encoding="utf-8")

    original_import = builtins.__import__
    def block_heavy_localization(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "isala_ocr.training.localization" or name.endswith(".training.localization"):
            raise ModuleNotFoundError("No module named 'isala_ocr.training.localization'")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", block_heavy_localization)
    details = localization_evaluation_details(
        tmp_path, predictions, model_id="field-lightweight", dataset_id=dataset_id,
        minimum_confidence=0.25, iou_threshold=0.75, split="test",
    )
    assert details["summary"]["true_positives"] == 1
    assert details["summary"]["false_negatives"] == 1
