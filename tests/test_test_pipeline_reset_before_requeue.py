""""Testen"/"Opnieuw testen" (single row) and "Geselecteerd opnieuw testen"
(a user-chosen subset of rows) must both reset any previous proefpagina
rerun of an origin before queuing a fresh one -- see ``_start_rerun()`` in
routes_test_pipeline.py -- so a retested row only ever has its latest attempt
on disk instead of piling up every previous one's disposable artifacts.

These tests never reach a successful requeue (no real DICOM exists under the
project's input directory in this fixture, so ``_start_rerun`` always errors
with "not_found") -- the point under test is that the *reset* step runs
before that lookup, which is directly observable even though the new rerun
itself fails to queue.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.test_pipeline_sources import (
    forget_test_pipeline_source, job_of_test_pipeline_source, origin_of_test_pipeline_source,
    record_test_pipeline_source,
)
from isala_ocr.training.webui import create_web_app

ORIGIN_A = "aaaaaaaaaaaaaaaaaaaaaaaa"
RERUN_A = "bbbbbbbbbbbbbbbbbbbbbbbb"
ORIGIN_B = "cccccccccccccccccccccccc"
RERUN_B = "dddddddddddddddddddddddd"


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    return app, workspace


def _seed_previous_rerun(workspace: Path, origin_id: str, rerun_id: str) -> None:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample({
        "sample_id": f"sample-{origin_id}", "source_id": origin_id, "profile": "cmr",
        "field_key": "field_a", "field_label": "Field A", "crop_path": "crops/x.png",
        "image_width": 8, "image_height": 8, "roi_x1": 0, "roi_y1": 0, "roi_x2": 4, "roi_y2": 4,
        "raw_ocr": "12", "raw_confidence": 0.9, "raw_variant": "original",
        "extraction_method": "dynamic_ocr", "status": "pending",
    })
    root = workspace / "extracted_output"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{origin_id}.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "measurements": {"field_a": {"display_name": "Field A", "parsed_value": "12", "raw_text": "12"}},
    }), encoding="utf-8")
    (root / f"{rerun_id}.json").write_text(json.dumps({
        "generated_at": "2026-01-02T00:00:00Z",
        "measurements": {"field_a": {"display_name": "Field A", "parsed_value": "13", "raw_text": "13"}},
    }), encoding="utf-8")
    record_test_pipeline_source(workspace, rerun_id, origin_source_id=origin_id, job_id="job-old")


def test_single_row_retest_resets_the_previous_rerun_before_attempting_a_new_one(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _seed_previous_rerun(workspace, ORIGIN_A, RERUN_A)
    assert (workspace / "extracted_output" / f"{RERUN_A}.json").is_file()

    response = app.test_client().post(f"/test-pipeline/opnieuw-testen/{ORIGIN_A}")
    assert response.status_code == 302, "no real input file in this fixture -- the requeue itself must still fail"

    assert origin_of_test_pipeline_source(workspace, RERUN_A) is None, (
        "the old rerun's tracking entry must be gone even though the new requeue failed"
    )
    assert job_of_test_pipeline_source(workspace, RERUN_A) is None
    assert not (workspace / "extracted_output" / f"{RERUN_A}.json").is_file(), (
        "the old rerun's extracted_output must have been cleared by the reset step"
    )


def test_bulk_retest_only_resets_the_selected_rows(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _seed_previous_rerun(workspace, ORIGIN_A, RERUN_A)
    _seed_previous_rerun(workspace, ORIGIN_B, RERUN_B)

    response = app.test_client().post(
        "/test-pipeline/geselecteerd-opnieuw-testen", data={"source_ids": [ORIGIN_A]}, follow_redirects=True,
    )
    assert response.status_code == 200

    assert origin_of_test_pipeline_source(workspace, RERUN_A) is None, "the selected row's previous rerun must be reset"
    assert not (workspace / "extracted_output" / f"{RERUN_A}.json").is_file()

    assert origin_of_test_pipeline_source(workspace, RERUN_B) == ORIGIN_B, (
        "a row that was not selected must be left completely untouched"
    )
    assert (workspace / "extracted_output" / f"{RERUN_B}.json").is_file()


def test_forgetting_a_source_also_deletes_its_tracked_input_duplicate(tmp_path: Path) -> None:
    """Nothing ever reads a rerun's duplicate DICOM again once its job has
    processed it, so leaving it under /input forever is pure clutter --
    identifying every such leftover file is exactly what made the
    proefpagina list slow to scan on a project with a long rerun history.
    ``record_test_pipeline_source(..., input_file_path=...)`` tracks where
    that duplicate lives; ``forget_test_pipeline_source()`` (called both by
    the explicit "verwijderen" action and by every fresh "Testen"/"Opnieuw
    testen" reset-before-requeue) must actually delete it, not just forget
    the tracking entry.
    """
    workspace = tmp_path / "workspace"
    duplicate = tmp_path / "input" / "test_abc123_000001.dcm"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"fake dicom bytes")

    record_test_pipeline_source(workspace, RERUN_A, origin_source_id=ORIGIN_A, input_file_path=duplicate)
    assert duplicate.is_file()

    forget_test_pipeline_source(workspace, RERUN_A)
    assert not duplicate.is_file(), "the tracked input duplicate must be deleted, not left behind"


def test_marking_reviewed_does_not_wipe_other_sources_tracked_input_files(tmp_path: Path) -> None:
    """A single-field write (reviewed_ids) must not silently drop the
    input_files dict the same JSON file also carries -- the exact bug
    pattern reviewed_ids itself was once bitten by (see
    test_reviewed_marker_survives_a_fresh_record_call_for_another_source in
    test_test_pipeline_mark_reviewed.py).
    """
    from isala_ocr.training.test_pipeline_sources import mark_test_pipeline_reviewed

    workspace = tmp_path / "workspace"
    duplicate = tmp_path / "input" / "test_abc123_000001.dcm"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"fake dicom bytes")
    record_test_pipeline_source(workspace, RERUN_A, origin_source_id=ORIGIN_A, input_file_path=duplicate)

    mark_test_pipeline_reviewed(workspace, RERUN_A, True)

    forget_test_pipeline_source(workspace, RERUN_A)
    assert not duplicate.is_file(), "input_files tracking must survive a reviewed-flag write in between"
