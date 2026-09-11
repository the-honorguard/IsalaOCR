from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_cell_training import (
    build_table_cell_dataset,
    table_cell_dataset_preview,
    table_cell_training_state,
)
from isala_ocr.training.table_model_comparison import (
    _current_evaluation_view,
    capture_current_detection_run,
    current_detection_context,
    review_comparison_issue,
    table_cell_comparison_state,
)
from isala_ocr.training.table_panels import save_panel_profile


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _seed_comparison_dataset(root: Path) -> str:
    dataset_id = "table-cells-versioned"
    base = root / "table_cell_datasets" / dataset_id
    (base / "images").mkdir(parents=True)
    Image.new("RGB", (100, 100), "white").save(base / "images" / "source-a__rv.png")
    _write_json(base / "manifest.json", {
        "schema_version": 2,
        "dataset_id": dataset_id,
        "type": "table_cell_detection",
        "path": f"table_cell_datasets/{dataset_id}",
        "created_at": "2026-08-14T10:00:00+00:00",
        "panel_profile_updated_at": "2026-08-14T09:00:00+00:00",
        "annotation_count": 1,
        "panel_count": 1,
        "review_fingerprint": "gt-v1",
        "training_feedback_fingerprint": "",
        "panels": [{
            "source_id": "source-a", "panel_id": "rv", "panel_name": "RV", "split": "train",
            "file_name": "source-a__rv.png", "box": [0, 0, 100, 100], "annotation_count": 1,
        }],
    })
    coco = {
        "images": [{"id": 1, "file_name": "source-a__rv.png", "width": 100, "height": 100}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 10, 10], "area": 100, "iscrowd": 0}],
        "categories": [{"id": 1, "name": "table_cell"}],
    }
    empty = {"images": [], "annotations": [], "categories": [{"id": 1, "name": "table_cell"}]}
    _write_json(base / "annotations" / "instance_train.json", coco)
    _write_json(base / "annotations" / "instance_val.json", empty)
    _write_json(base / "annotations" / "instance_test.json", empty)
    _write_json(base / "validation.json", {"valid": True})
    (root / "table_cell_datasets" / "latest.txt").write_text(dataset_id + "\n", encoding="ascii")

    db = TrainingDatabase(root / "samples.sqlite3")
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO detection_sources(source_id,image_width,image_height,render_path,detector_version,
                token_count,block_count,relation_count,detected_at,updated_at,review_completed)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            ("source-a", 100, 100, "source_renders/source-a.png", "ppstructure", 0, 2, 0,
             "2026-08-14T11:00:00+00:00", "2026-08-14T11:00:00+00:00", 1),
        )
    return dataset_id


def _model(root: Path, model_id: str, run_id: str, dataset_id: str, activated_at: str) -> dict:
    inf = root / "table_cell_models" / model_id / "inference"
    inf.mkdir(parents=True, exist_ok=True)
    (inf / "inference.yml").write_text("model: table\n", encoding="utf-8")
    payload = {
        "model_id": model_id,
        "model_name": "RT-DETR-L_wireless_table_cell_det",
        "run_id": run_id,
        "dataset_id": dataset_id,
        "device": "gpu",
        "inference_dir": f"table_cell_models/{model_id}/inference",
        "created_at": activated_at,
        "activated_at": activated_at,
        "active": True,
    }
    _write_json(root / "table_cell_models" / model_id / "model.json", payload)
    return payload


def _diagnostic(root: Path, *, model_id: str, model_run_id: str, dataset_id: str, batch: str, detected_at: str, candidates: list[dict]) -> None:
    _write_json(root / "localization_detections" / "source-a.json", {
        "schema_version": "3.1-localization-run-aware",
        "source_id": "source-a",
        "detection_batch_id": batch,
        "detected_at": detected_at,
        "active_table_cell_model": {
            "model_id": model_id,
            "model_name": "RT-DETR-L_wireless_table_cell_det",
            "run_id": model_run_id,
            "dataset_id": dataset_id,
            "activated_at": detected_at,
        },
        "candidates": candidates,
    })


def test_activating_v2_never_relabels_v1_predictions_as_current_v2(tmp_path: Path) -> None:
    dataset_id = _seed_comparison_dataset(tmp_path)
    _diagnostic(
        tmp_path, model_id="model-v1", model_run_id="train-v1", dataset_id=dataset_id,
        batch="batch-v1", detected_at="2026-08-14T11:00:00+00:00",
        candidates=[
            {"candidate_id": "hit", "source_kind": "table_cell", "confidence": 0.95, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
            {"candidate_id": "extra", "source_kind": "table_cell", "confidence": 0.80, "x1": 60, "y1": 60, "x2": 70, "y2": 70},
        ],
    )
    v1 = capture_current_detection_run(tmp_path)
    assert v1 and v1["model_id"] == "model-v1"

    v2 = _model(tmp_path, "model-v2", "train-v2", dataset_id, "2026-08-14T12:00:00+00:00")
    _write_json(tmp_path / "table_cell_models" / "active.json", v2)

    context = current_detection_context(tmp_path)
    assert context["model_id"] == "model-v1"
    assert context["stale_against_active_model"] is True

    state = table_cell_comparison_state(tmp_path)
    assert state["ready"] is False
    assert state["detection_stale"] is True
    assert state["active_model"]["model_id"] == "model-v2"
    assert state["detection_context"]["model_id"] == "model-v1"
    assert all(run.get("model_id") != "model-v2" for run in state.get("runs", []) if run.get("run_id") != "step4-baseline")


def test_new_v2_detection_gets_fresh_active_review_and_v1_becomes_read_only_history(tmp_path: Path) -> None:
    dataset_id = _seed_comparison_dataset(tmp_path)
    v2 = _model(tmp_path, "model-v2", "train-v2", dataset_id, "2026-08-14T12:00:00+00:00")

    _diagnostic(
        tmp_path, model_id="model-v1", model_run_id="train-v1", dataset_id=dataset_id,
        batch="batch-v1", detected_at="2026-08-14T11:00:00+00:00",
        candidates=[
            {"candidate_id": "hit", "source_kind": "table_cell", "confidence": 0.95, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
            {"candidate_id": "extra", "source_kind": "table_cell", "confidence": 0.80, "x1": 60, "y1": 60, "x2": 70, "y2": 70},
        ],
    )
    v1_run = capture_current_detection_run(tmp_path)
    assert v1_run
    v1_state = table_cell_comparison_state(tmp_path, candidate_run_id=v1_run["run_id"])
    v1_issue = v1_state["issue_panels"][0]["issues"][0]
    review_comparison_issue(tmp_path, v1_run["run_id"], v1_issue["issue_id"], "model_error")
    reviewed_state = table_cell_comparison_state(tmp_path, candidate_run_id=v1_run["run_id"])
    assert reviewed_state["training_report"]["model_error"] == 1
    assert reviewed_state["training_report"]["open"] == 0

    _write_json(tmp_path / "table_cell_models" / "active.json", v2)
    _diagnostic(
        tmp_path, model_id="model-v2", model_run_id="train-v2", dataset_id=dataset_id,
        batch="batch-v2", detected_at="2026-08-14T12:05:00+00:00",
        candidates=[
            {"candidate_id": "hit-v2", "source_kind": "table_cell", "confidence": 0.98, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
        ],
    )
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    with db.connect() as conn:
        conn.execute("UPDATE detection_sources SET detected_at=?,updated_at=? WHERE source_id='source-a'", (
            "2026-08-14T12:05:00+00:00", "2026-08-14T12:05:00+00:00"
        ))

    state = table_cell_comparison_state(tmp_path)
    assert state["ready"] is True
    assert state["candidate"]["model_id"] == "model-v2"
    assert state["candidate"]["run_id"] != v1_run["run_id"]
    assert state["issue_count"] == 0
    assert state["reviewed_issue_count"] == 0
    assert state["review_complete"] is True
    assert any(item["run_id"] == v1_run["run_id"] for item in state["history"])

    try:
        review_comparison_issue(tmp_path, v1_run["run_id"], v1_issue["issue_id"], "model_error")
    except ValueError as exc:
        assert "alleen-lezen" in str(exc)
    else:
        raise AssertionError("historische run mocht niet opnieuw beoordeeld worden")


def _seed_initial_training_gt(root: Path) -> None:
    save_panel_profile(
        root,
        panels=[{"panel_id": "rv", "name": "RV", "x1": 0.0, "y1": 0.0, "x2": 1.0, "y2": 1.0}],
        reference_source_id="source-a", reference_width=100, reference_height=100,
    )
    renders = root / "source_renders"
    renders.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 100), "white").save(renders / "source-a.png")
    db = TrainingDatabase(root / "samples.sqlite3")
    db.replace_localization_detection(
        {"source_id": "source-a", "image_width": 100, "image_height": 100,
         "render_path": "source_renders/source-a.png", "detector_version": "ppstructure", "token_count": 0},
        [{"candidate_id": "cell-1", "source_id": "source-a", "confidence": 0.95, "source_kind": "table_cell",
          "source_refs": ["table:t:cell:1"], "crop_path": "", "x1": 10, "y1": 10, "x2": 30, "y2": 30}],
        [],
    )
    db.review_detection_candidate(source_id="source-a", candidate_id="cell-1", review_status="correct")
    db.set_detection_source_review_completed("source-a", True)


def test_completed_step7_model_errors_change_only_train_weighting(tmp_path: Path) -> None:
    _seed_initial_training_gt(tmp_path)
    first = build_table_cell_dataset(tmp_path)
    run_id = "detect-reviewed-v1"
    run = {
        "schema_version": 2,
        "run_id": run_id,
        "label": "model-v1 · Stap 3",
        "model_id": "model-v1",
        "model_name": "RT-DETR-L_wireless_table_cell_det",
        "dataset_id": first["dataset_id"],
        "source": "step3_localization_diagnostics",
        "created_at": "2026-08-14T13:00:00+00:00",
        "iou_threshold": 0.5,
        "geometry_iou": 0.75,
        "metrics": {"review_needed": 1},
        "panels": [{
            "source_id": "source-a", "panel_id": "rv", "panel_name": "RV", "split": "train",
            "file_name": "source-a__rv.png", "panel_box": [0, 0, 100, 100], "width": 100, "height": 100,
            "ground_truth": [{"gt_id": "gt-1", "box": [10, 10, 30, 30]}],
            "predictions": [], "matches": [],
            "issues": [{
                "issue_id": "fn-hard", "type": "fn", "label": "GT-cel gemist (FN)",
                "prediction_box": None, "gt_boxes": [[10, 10, 30, 30]], "confidence": 0.0, "iou": 0.0,
                "source_id": "source-a", "panel_id": "rv", "panel_name": "RV", "file_name": "source-a__rv.png",
                "width": 100, "height": 100, "split": "train",
            }],
            "tp": 0, "fp": 0, "fn": 1, "direct_correct": 0, "geometry_mismatch": 0, "merged": 0,
        }],
    }
    # The re-evaluation on load recomputes issue ids deterministically (see
    # _issue_identifier); a hand-typed id like the legacy "fn-hard" above never
    # matches, so compute the real, current issue_id the same way the app does
    # before writing the matching review.
    upgraded = _current_evaluation_view(run)
    real_issue_id = upgraded["panels"][0]["issues"][0]["issue_id"]
    _write_json(tmp_path / "table_cell_comparisons" / "runs" / f"{run_id}.json", run)
    _write_json(tmp_path / "table_cell_comparisons" / "reviews.json", {
        run_id: {real_issue_id: {"decision": "model_error", "reviewed_at": "2026-08-14T13:05:00+00:00"}}
    })

    preview = table_cell_dataset_preview(tmp_path)
    assert preview["training_feedback"]["available"] is True
    assert preview["training_feedback"]["model_error_count"] == 1
    assert table_cell_training_state(tmp_path)["dataset_current"] is False

    second = build_table_cell_dataset(tmp_path)
    assert second["annotation_count"] == 1
    # The hard-example replay policy (table_hard_negative_policy) now performs
    # dynamic, in-memory weighted resampling at train time instead of writing
    # physical duplicate PNG/COCO copies, so the panel is still flagged as a
    # hard example but no extra images are baked into the dataset itself.
    assert second["hard_example_panel_count"] == 1
    assert second["hard_example_image_count"] == 0
    assert second["hard_example_replay_draw_count"] >= 1
    assert second["training_annotation_count"] == 1
    train = json.loads((tmp_path / second["path"] / "annotations" / "instance_train.json").read_text(encoding="utf-8"))
    val = json.loads((tmp_path / second["path"] / "annotations" / "instance_val.json").read_text(encoding="utf-8"))
    test = json.loads((tmp_path / second["path"] / "annotations" / "instance_test.json").read_text(encoding="utf-8"))
    assert len(train["images"]) == 1
    assert len(train["annotations"]) == 1
    assert len(val["images"]) == 0
    assert len(test["images"]) == 0


def test_training_runtime_and_powershell_support_continuation_from_active_model() -> None:
    root = Path(__file__).resolve().parents[1]
    runner = (root / "automation/training_runtime/table_cell_runner.py").read_text(encoding="utf-8")
    script = (root / "automation/powershell/train-table-cell-model.ps1").read_text(encoding="utf-8")
    assert '--parent-model-id' in runner
    assert '--training-mode' in runner
    assert '--learning-rate' in runner
    assert '$TrainingMode = "continue"' in script
    assert '$LearningRate = 0.00003' in script
    assert 'Continuing from active custom model' in script
