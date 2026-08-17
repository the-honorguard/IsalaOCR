from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.localization_dataset import (
    build_localization_dataset,
    derived_detection_gate_state,
    diagnose_prediction_file,
    evaluate_prediction_file,
)


THRESHOLDS = {
    "minimum_test_images": 3,
    "minimum_test_rois": 3,
    "minimum_recall": 0.95,
    "minimum_precision": 0.90,
    "minimum_auto_accept_rate": 0.85,
    "maximum_false_positives_per_image": 1.0,
}


def _prepare_workspace(root: Path) -> tuple[Path, dict, dict[str, list[dict]]]:
    workspace = root / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for index in range(14):
        source_id = f"source-{index:02d}"
        render = workspace / "source_renders" / f"{source_id}.png"
        render.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(render), np.zeros((120, 320, 3), dtype=np.uint8))
        source = {
            "source_id": source_id,
            "image_width": 320,
            "image_height": 120,
            "render_path": render.relative_to(workspace).as_posix(),
            "detector_version": "quality-test",
            "token_count": 0,
        }
        db.replace_localization_detection(source, [], [])
        db.add_detection_annotation(source_id=source_id, box=(20, 20, 100, 50))
        db.set_detection_source_review_completed(source_id, True)
    manifest = build_localization_dataset(workspace)
    predictions = {
        source_id: [{"score": 0.10, "coordinate": [20, 20, 100, 50], "bbox_format": "xyxy"}]
        for source_id in manifest["source_splits"]
    }
    return workspace, manifest, predictions


def test_trained_evaluation_replaces_stale_gate_reason_with_metric_failures(tmp_path: Path) -> None:
    workspace, manifest, predictions = _prepare_workspace(tmp_path)
    db = TrainingDatabase(workspace / "samples.sqlite3")
    db.set_detection_gate(False, reason="Detection ground truth of scope is gewijzigd; evalueer opnieuw.")
    path = workspace / "predictions.json"
    path.write_text(json.dumps({"threshold": 0.01, "predictions": predictions}), encoding="utf-8")

    result = evaluate_prediction_file(
        workspace,
        path,
        model_id="field-test",
        dataset_id=manifest["dataset_id"],
        minimum_confidence=0.25,
        thresholds=THRESHOLDS,
        split="test",
    )
    assert result["metrics"]["scored_predictions"] == 0
    gate = derived_detection_gate_state(workspace, thresholds=THRESHOLDS)
    assert gate["state"] == "failed"
    assert "haalt de detection gate niet" in gate["reason"]
    assert "ground truth of scope is gewijzigd" not in gate["reason"]
    assert gate["fingerprint_current"] is True


def test_threshold_sweep_exposes_low_confidence_predictions_on_all_splits(tmp_path: Path) -> None:
    workspace, manifest, predictions = _prepare_workspace(tmp_path)
    path = workspace / "predictions.json"
    path.write_text(json.dumps({"threshold": 0.01, "predictions": predictions}), encoding="utf-8")

    diagnostic = diagnose_prediction_file(
        workspace,
        path,
        model_id="field-test",
        dataset_id=manifest["dataset_id"],
        confidence_thresholds=[0.01, 0.10, 0.25],
        thresholds=THRESHOLDS,
    )
    assert set(diagnostic["splits"]) == {"train", "val", "test"}
    for split in ("train", "val", "test"):
        assert diagnostic["splits"][split]
        low = diagnostic["splits"][split][0]["metrics"]
        high = diagnostic["splits"][split][-1]["metrics"]
        assert low["scored_predictions"] > 0
        assert low["recall"] == 1.0
        assert high["scored_predictions"] == 0
        assert high["recall"] == 0.0
    assert any("onder 0.25" in text for text in diagnostic["diagnosis"])
    assert (workspace / "localization_diagnostics" / "latest_trained.json").is_file()


def test_ground_truth_change_marks_evaluation_stale(tmp_path: Path) -> None:
    workspace, manifest, predictions = _prepare_workspace(tmp_path)
    path = workspace / "predictions.json"
    path.write_text(json.dumps({"threshold": 0.01, "predictions": predictions}), encoding="utf-8")
    evaluate_prediction_file(
        workspace,
        path,
        model_id="field-test",
        dataset_id=manifest["dataset_id"],
        minimum_confidence=0.10,
        thresholds=THRESHOLDS,
        split="test",
    )

    test_source = next(source_id for source_id, split in manifest["source_splits"].items() if split == "test")
    db = TrainingDatabase(workspace / "samples.sqlite3")
    db.add_detection_annotation(source_id=test_source, box=(150, 60, 230, 90))
    db.set_detection_source_review_completed(test_source, True)
    gate = derived_detection_gate_state(workspace, thresholds=THRESHOLDS)
    assert gate["state"] == "stale"
    assert gate["fingerprint_current"] is False


def test_quality_page_polls_component_state_and_never_reloads_page() -> None:
    root = Path(__file__).resolve().parents[1]
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/react_localization_quality.html").read_text(encoding="utf-8")
    source = (root / "frontend/src/localization-quality.ts").read_text(encoding="utf-8")
    built = (root / "application/src/isala_ocr/training/static/react/localization-quality.js").read_text(encoding="utf-8")
    assert "/api/v2/localization/quality" in webui
    assert 'id="react-localization-quality"' in template
    assert 'new EventSource' not in source
    assert 'window.setTimeout(() => this.refresh(false), delay)' in source
    assert 'active ? 2500 : 12000' in source
    assert 'document.hidden ? 30000' in source
    assert 'fetch("/api/v2/localization/quality"' in source
    assert 'this.startJob("9")' in source
    assert 'this.startJob("11")' in source
    assert "window.location.reload" not in source
    assert "window.location.reload" not in built
    assert "React.Fragment" not in source
    assert "ReactDOM.createRoot" not in source
