from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from isala_ocr.models import Box
from isala_ocr.training.db import SCHEMA_VERSION, TrainingDatabase
from isala_ocr.training.localization import LocalizationCandidate, passes_detection_gate
from isala_ocr.training.localization_dataset import (
    _split_for_source, build_localization_dataset, validate_localization_dataset,
)
from isala_ocr.training.mapping import resolve_value_roi_box

ROOT = Path(__file__).resolve().parents[1]


def _source(workspace: Path, db: TrainingDatabase, source_id: str = "source") -> dict:
    render = workspace / "source_renders" / f"{source_id}.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((120, 320, 3), dtype=np.uint8)
    assert cv2.imwrite(str(render), image)
    source = {
        "source_id": source_id,
        "image_width": 320,
        "image_height": 120,
        "render_path": render.relative_to(workspace).as_posix(),
        "detector_version": "field-localization-test",
        "token_count": 0,
    }
    db.replace_localization_detection(source, [], [])
    return source


def test_schema_v11_has_separate_detection_and_recognition_entities(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    assert SCHEMA_VERSION == 14
    with db.connect() as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for name in (
        "detection_sources", "detection_candidates", "detection_reviews", "detection_annotations",
        "localization_datasets", "localization_models", "localization_evaluations", "samples",
    ):
        assert name in tables


def test_localization_candidate_payload_contains_geometry_but_no_ocr_value() -> None:
    payload = LocalizationCandidate(
        candidate_id="c", source_id="s", box=Box(10, 20, 60, 40), confidence=0.9,
        source_kind="text_geometry", source_refs=("ocr:1",),
    ).as_dict()
    assert payload["x1"] == 10 and payload["x2"] == 60
    assert "text" not in payload
    assert "raw_ocr" not in payload
    assert "field_key" not in payload
    assert "parsed_value" not in payload


def test_reviewed_detection_geometry_becomes_ground_truth_and_invalidates_gate(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db)
    db.replace_localization_detection(
        source,
        [{
            "candidate_id": "candidate", "source_id": "source", "confidence": 0.95,
            "source_kind": "trained_detector", "source_refs": ["model:x"], "crop_path": "",
            "x1": 90, "y1": 20, "x2": 150, "y2": 45,
        }],
        [],
    )
    db.set_detection_gate(True, reason="previous pass", evaluation_id="old")
    db.review_detection_candidate(
        source_id="source", candidate_id="candidate", review_status="adjusted",
        corrected_box=(94, 21, 154, 46), reason_code="misplaced",
    )
    annotations = db.list_detection_annotations("source")
    assert len(annotations) == 1
    assert [annotations[0][k] for k in ("x1", "y1", "x2", "y2")] == [94, 21, 154, 46]
    assert annotations[0]["review_status"] == "adjusted"
    assert db.detection_gate()["ready"] is False
    assert "ground truth" in db.detection_gate()["reason"]


def test_manual_missing_roi_is_positive_ground_truth_and_rejected_candidate_is_not(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db)
    db.replace_localization_detection(
        source,
        [{
            "candidate_id": "false", "source_id": "source", "confidence": 0.8,
            "source_kind": "text_geometry", "source_refs": [], "crop_path": "",
            "x1": 20, "y1": 20, "x2": 70, "y2": 40,
        }],
        [],
    )
    db.review_detection_candidate(
        source_id="source", candidate_id="false", review_status="rejected",
        reason_code="false_positive",
    )
    db.add_detection_annotation(source_id="source", box=(100, 30, 160, 55), reason_code="split_field")
    annotations = db.list_detection_annotations("source")
    assert len(annotations) == 1
    assert annotations[0]["provenance"] == "added"
    counts = db.detection_review_counts("source")
    assert counts["rejected"] == 1
    assert counts["added"] == 1
    assert counts["positive"] == 1


def test_localization_dataset_is_full_image_coco_with_single_generic_class(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    chosen: dict[str, str] = {}
    index = 0
    while set(chosen) != {"train", "val", "test"}:
        source_id = f"s{index}"
        chosen.setdefault(_split_for_source(source_id), source_id)
        index += 1
    for source_id in chosen.values():
        _source(workspace, db, source_id)
        db.add_detection_annotation(source_id=source_id, box=(10, 10, 80, 35))
        db.set_detection_source_review_completed(source_id, True)
    manifest = build_localization_dataset(workspace)
    assert manifest["format"] == "COCODetDataset"
    assert manifest["class_names"] == ["field_roi"]
    assert manifest["annotation_count"] == 3
    dataset_root = workspace / manifest["path"]
    payloads = [json.loads((dataset_root / "annotations" / f"instance_{split}.json").read_text()) for split in ("train", "val", "test")]
    categories = {tuple((item["id"], item["name"]) for item in payload["categories"]) for payload in payloads}
    assert categories == {((1, "field_roi"),)}
    assert sum(len(payload["annotations"]) for payload in payloads) == 3
    # PaddleX COCODetDataset joins dataset_dir / "images" / file_name.
    # file_name must therefore be relative to the images directory itself.
    for payload in payloads:
        for image in payload["images"]:
            assert Path(image["file_name"]).name == image["file_name"]
            assert not image["file_name"].startswith("images/")
            assert (dataset_root / "images" / image["file_name"]).is_file()
    report = validate_localization_dataset(workspace)
    assert report["status"] == "ok"



def test_reviewed_ground_truth_survives_candidate_disappearance_as_persistent_annotation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db)
    db.replace_localization_detection(source, [{
        "candidate_id": "old", "source_id": "source", "confidence": 0.9,
        "source_kind": "text_geometry", "source_refs": [], "crop_path": "",
        "x1": 20, "y1": 20, "x2": 80, "y2": 42,
    }], [])
    db.review_detection_candidate(
        source_id="source", candidate_id="old", review_status="adjusted",
        corrected_box=(22, 19, 84, 44), reason_code="misplaced",
    )
    db.replace_localization_detection(source, [{
        "candidate_id": "new", "source_id": "source", "confidence": 0.8,
        "source_kind": "trained_detector", "source_refs": [], "crop_path": "",
        "x1": 180, "y1": 70, "x2": 230, "y2": 92,
    }], [])
    annotations = db.list_detection_annotations("source", active_only=True)
    assert len(annotations) == 1
    assert annotations[0]["candidate_id"] == ""
    assert [annotations[0][key] for key in ("x1", "y1", "x2", "y2")] == [22, 19, 84, 44]
    counts = db.detection_review_counts("source")
    assert counts["positive"] == 1
    assert counts["persistent"] == 1
    db.delete_manual_detection_annotation(str(annotations[0]["annotation_id"]))
    assert db.list_detection_annotations("source", active_only=True) == []


def test_repeated_localization_dataset_builds_do_not_collide(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    for split in ("train", "val"):
        index = 0
        while True:
            source_id = f"{split}-{index}"
            if _split_for_source(source_id) == split:
                break
            index += 1
        _source(workspace, db, source_id)
        db.add_detection_annotation(source_id=source_id, box=(10, 10, 80, 35))
        db.set_detection_source_review_completed(source_id, True)
    first = build_localization_dataset(workspace)
    second = build_localization_dataset(workspace)
    assert first["dataset_id"] != second["dataset_id"]
    assert (workspace / first["path"]).is_dir()
    assert (workspace / second["path"]).is_dir()

def test_detection_gate_requires_metrics_and_minimum_independent_test_volume() -> None:
    thresholds = {
        "minimum_test_images": 3,
        "minimum_test_rois": 10,
        "minimum_recall": 0.95,
        "minimum_precision": 0.90,
        "minimum_auto_accept_rate": 0.85,
        "maximum_false_positives_per_image": 1.0,
    }
    strong_but_tiny = {
        "evaluated_images": 1, "ground_truth_rois": 2, "recall": 1.0, "precision": 1.0,
        "auto_accept_rate": 1.0, "false_positives_per_image": 0.0,
    }
    passed, failures = passes_detection_gate(strong_but_tiny, thresholds)
    assert passed is False
    assert any("evaluated_images" in item for item in failures)
    assert any("ground_truth_rois" in item for item in failures)
    strong = {**strong_but_tiny, "evaluated_images": 5, "ground_truth_rois": 40}
    assert passes_detection_gate(strong, thresholds)[0] is True


def test_pipeline_b_roi_geometry_must_come_from_pipeline_a(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db)
    semantic_value = {
        "block_id": "value", "source_id": "source", "block_type": "semantic", "role": "value",
        "text": "12.3 ml", "normalized_text": "12 3 ml", "confidence": 0.99,
        "x1": 100, "y1": 20, "x2": 150, "y2": 40, "line_index": 0, "sequence_index": 1,
        "parent_block_id": "", "context_text": "", "crop_path": "",
    }
    db.replace_generic_detection(source, [semantic_value], [])
    try:
        resolve_value_roi_box(db, "value", 320, 120)
    except ValueError as exc:
        assert "Pipeline-A ROI" in str(exc)
    else:
        raise AssertionError("Pipeline B must not synthesize crop geometry")

    # Re-add localization after semantic detection updated the shared source row.
    db.replace_localization_detection(
        source,
        [{
            "candidate_id": "loc", "source_id": "source", "confidence": 0.95,
            "source_kind": "trained_detector", "source_refs": [], "crop_path": "",
            "x1": 96, "y1": 18, "x2": 154, "y2": 43,
        }],
        [],
    )
    box, diagnostics = resolve_value_roi_box(db, "value", 320, 120)
    assert box == Box(96, 18, 154, 43)
    assert diagnostics["geometry_source"].startswith("pipeline_a_candidate")


def test_detection_review_studio_supports_geometry_editing_and_table_overlays() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    for text in ("Field candidates", "Table regions", "Table cells"):
        assert text in template
    # These reason labels now live in routes_detection_review.py (split out of webui.py).
    webui = (ROOT / "application/src/isala_ocr/training/routes_detection_review.py").read_text(encoding="utf-8")
    for text in ("Te klein", "Te groot", "Meerdere velden/cellen samengevoegd", "Eén veld opgesplitst", "Tabel/cel fout"):
        assert text in webui
    assert 'id="dock-reject-reason"' in template
    assert "resize-handle" in template
    assert "manual" in template.lower()
    assert "crop-preview" in template


def test_menu_and_web_navigation_have_hard_pipeline_separator() -> None:
    menu = (ROOT / "automation/powershell/training-menu.ps1").read_text(encoding="utf-8")
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    # The recognition-gate guard lives in routes_jobs.py now (split out of webui.py).
    routes_jobs = (ROOT / "application/src/isala_ocr/training/routes_jobs.py").read_text(encoding="utf-8")
    assert "MODEL FACTORY · GEOMETRIE" in menu
    assert "MODEL FACTORY · RECOGNITION" in menu
    assert "FASE 2 · APPLICATION PROCESSING · OPTIONEEL" in menu
    assert '"20": "Mappinggegevens voorbereiden na detectiepoort"' in webui
    assert 'action_id in {"24", "25", "26", "27", "28"}' in routes_jobs
    assert "pipeline_gate_global" in webui
    assert "MODEL FACTORY · DETECTIE & CROPS" in base
    assert "MODEL FACTORY · RECOGNITION" in base


def test_labeler_remains_lightweight_despite_detection_review_ui() -> None:
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "infrastructure/docker/Dockerfile.labeler").read_text(encoding="utf-8")
    assert "from .localization import" not in webui
    assert '"opencv-python>=' not in dockerfile.lower()
    assert "opencv-python-headless" in dockerfile.lower()
    assert "paddleocr" not in "\n".join(
        line.lower() for line in dockerfile.splitlines() if not line.lstrip().startswith("#")
    )


def test_localization_training_runtime_uses_paddlex_object_detection() -> None:
    runner = (ROOT / "automation/training_runtime/localization_runner.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "infrastructure/docker/Dockerfile.training").read_text(encoding="utf-8")
    assert "PicoDet-S" in runner
    assert "object_detection" in runner
    assert 'Global.mode=train' in runner
    assert 'Global.mode=check_dataset' in runner
    assert "PaddleDetection" in dockerfile
