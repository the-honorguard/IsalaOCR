from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from isala_ocr.training.db import SCHEMA_VERSION, TrainingDatabase
from isala_ocr.training.localization_dataset import _evaluate_prediction_map, _split_for_source, build_localization_dataset
from isala_ocr.training.mapping import resolve_value_roi_box

ROOT = Path(__file__).resolve().parents[1]


def _source(workspace: Path, db: TrainingDatabase, source_id: str) -> dict:
    render = workspace / "source_renders" / f"{source_id}.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    image = np.zeros((140, 360, 3), dtype=np.uint8)
    assert cv2.imwrite(str(render), image)
    source = {
        "source_id": source_id, "image_width": 360, "image_height": 140,
        "render_path": render.relative_to(workspace).as_posix(),
        "detector_version": "scope-test", "token_count": 0,
    }
    db.replace_localization_detection(source, [], [])
    return source


def _candidate(candidate_id: str, box: tuple[int, int, int, int]) -> dict:
    x1, y1, x2, y2 = box
    return {
        "candidate_id": candidate_id, "source_id": "unused", "confidence": 0.95,
        "source_kind": "text_geometry", "source_refs": [], "crop_path": "",
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
    }


def test_schema_v12_separates_geometry_review_from_scope_relevance(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    assert SCHEMA_VERSION == 14
    with db.connect() as conn:
        review_columns = {row["name"] for row in conn.execute("PRAGMA table_info(detection_reviews)")}
        annotation_columns = {row["name"] for row in conn.execute("PRAGMA table_info(detection_annotations)")}
    assert {"relevance_status", "relevance_reason"} <= review_columns
    assert "training_role" in annotation_columns


def test_out_of_scope_candidate_is_negative_for_current_project(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db, "source")
    item = _candidate("date", (20, 10, 110, 35)); item["source_id"] = "source"
    db.replace_localization_detection(source, [item], [])

    # A reason is deliberately optional. The model learns only positive/negative.
    db.review_detection_candidate(
        source_id="source", candidate_id="date", review_status="correct",
        relevance_status="irrelevant",
    )
    candidate = db.get_detection_candidate("source", "date")
    assert candidate is not None
    assert candidate["review_status"] == "correct"
    assert candidate["relevance_status"] == "irrelevant"
    assert db.list_detection_annotations("source") == []
    all_annotations = db.list_detection_annotations("source", include_ignored=True)
    assert len(all_annotations) == 1
    assert all_annotations[0]["training_role"] == "negative"
    counts = db.detection_review_counts("source")
    assert counts["positive"] == 0
    assert counts["negative"] == 1
    assert counts["pending"] == 0


def test_optional_scope_reason_is_stored_for_analysis(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db, "source")
    item = _candidate("date", (20, 10, 110, 35)); item["source_id"] = "source"
    db.replace_localization_detection(source, [item], [])
    db.review_detection_candidate(
        source_id="source", candidate_id="date", review_status="correct",
        relevance_status="irrelevant", relevance_reason="date_time",
    )
    candidate = db.get_detection_candidate("source", "date")
    assert candidate and candidate["relevance_reason"] == "date_time"


def test_irrelevant_geometry_cannot_flow_into_mapping_roi(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    source = _source(workspace, db, "source")
    db.replace_generic_detection(source, [{
        "block_id": "value", "source_id": "source", "block_type": "semantic", "role": "value",
        "text": "5 Jun 2025", "normalized_text": "5 jun 2025", "confidence": 0.99,
        "x1": 20, "y1": 10, "x2": 110, "y2": 35, "line_index": 0, "sequence_index": 0,
        "parent_block_id": "", "context_text": "", "crop_path": "",
    }], [])
    item = _candidate("date", (18, 8, 114, 38)); item["source_id"] = "source"
    db.replace_localization_detection(source, [item], [])
    db.review_detection_candidate(
        source_id="source", candidate_id="date", review_status="correct",
        relevance_status="irrelevant",
    )
    with pytest.raises(ValueError, match="Pipeline-A ROI"):
        resolve_value_roi_box(db, "value", 360, 140)


def test_project_specific_negative_regions_become_background_on_complete_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    selected: dict[str, str] = {}
    i = 0
    while set(selected) != {"train", "val", "test"}:
        sid = f"scope-{i}"
        selected.setdefault(_split_for_source(sid), sid)
        i += 1
    for sid in selected.values():
        source = _source(workspace, db, sid)
        positive = _candidate(f"positive-{sid}", (20, 60, 100, 90)); positive["source_id"] = sid
        negative = _candidate(f"negative-{sid}", (200, 10, 300, 35)); negative["source_id"] = sid
        db.replace_localization_detection(source, [positive, negative], [])
        db.review_detection_candidate(source_id=sid, candidate_id=positive["candidate_id"], review_status="correct")
        db.review_detection_candidate(
            source_id=sid, candidate_id=negative["candidate_id"], review_status="correct",
            relevance_status="irrelevant", relevance_reason="date_time",
        )
        db.set_detection_source_review_completed(sid, True)
    manifest = build_localization_dataset(workspace)
    assert manifest["annotation_count"] == 3
    assert manifest["positive_review_count"] == 3
    assert manifest["negative_review_count"] == 3
    assert manifest["ignored_annotation_count"] == 0
    assert manifest["full_source_image_count"] == 3


def test_evaluation_counts_project_specific_negative_prediction_as_false_positive(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    db = TrainingDatabase(workspace / "samples.sqlite3")
    i = 0
    while True:
        sid = f"eval-{i}"
        if _split_for_source(sid) == "test": break
        i += 1
    source = _source(workspace, db, sid)
    positive = _candidate("positive", (20, 60, 100, 90)); positive["source_id"] = sid
    negative = _candidate("date", (200, 10, 300, 35)); negative["source_id"] = sid
    db.replace_localization_detection(source, [positive, negative], [])
    db.review_detection_candidate(source_id=sid, candidate_id="positive", review_status="correct")
    db.review_detection_candidate(source_id=sid, candidate_id="date", review_status="correct", relevance_status="irrelevant")
    result = _evaluate_prediction_map(
        workspace,
        {sid: [{"coordinate": [20, 60, 100, 90]}, {"coordinate": [200, 10, 300, 35]}]},
        kind="baseline", split="test",
    )
    assert result["metrics"]["true_positives"] == 1
    assert result["metrics"]["false_positives"] == 1


def test_detection_review_ui_exposes_exception_first_commands_and_optional_incorrect_reason() -> None:
    template = (ROOT / "application/src/isala_ocr/training/templates/detection_review_studio.html").read_text(encoding="utf-8")
    assert 'id="dock-include"' in template
    assert 'id="dock-irrelevant"' in template
    assert 'id="dock-reject"' in template
    assert 'id="dock-reject-reason"' in template
    assert 'id="dock-edit"' in template
    assert "Reden optioneel" in template
    assert "Rest standaard includeren" in template
    assert "Afbeelding klaar" in template


def test_existing_v11_detection_tables_gain_scope_columns(tmp_path: Path) -> None:
    import sqlite3
    path = tmp_path / "samples.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key,value) VALUES('schema_version','11');
        CREATE TABLE detection_reviews (
            review_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, candidate_id TEXT NOT NULL DEFAULT '',
            review_status TEXT NOT NULL, reason_code TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
            original_x1 INTEGER NOT NULL, original_y1 INTEGER NOT NULL, original_x2 INTEGER NOT NULL, original_y2 INTEGER NOT NULL,
            corrected_x1 INTEGER NOT NULL, corrected_y1 INTEGER NOT NULL, corrected_x2 INTEGER NOT NULL, corrected_y2 INTEGER NOT NULL,
            reviewed_at TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE detection_annotations (
            annotation_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, candidate_id TEXT NOT NULL DEFAULT '',
            review_id TEXT NOT NULL DEFAULT '', provenance TEXT NOT NULL,
            x1 INTEGER NOT NULL, y1 INTEGER NOT NULL, x2 INTEGER NOT NULL, y2 INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit(); conn.close()
    TrainingDatabase(path)
    with sqlite3.connect(path) as check:
        review_columns = {row[1] for row in check.execute("PRAGMA table_info(detection_reviews)")}
        annotation_columns = {row[1] for row in check.execute("PRAGMA table_info(detection_annotations)")}
        version = check.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
        assert version == "14"
    assert {"relevance_status", "relevance_reason"} <= review_columns
    assert "training_role" in annotation_columns
