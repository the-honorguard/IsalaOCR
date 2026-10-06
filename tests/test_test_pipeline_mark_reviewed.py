"""A "getest" row whose datablok differs from its trainingspipeline origin
isn't always something to fix -- sometimes the retest legitimately found
*more* values than the training data has, because the training data itself
is incomplete. ``/test-pipeline/beoordeeld/<source_id>`` lets the user mark
such a compare run as reviewed from the compare screen, so the list
(``/test-pipeline``) can separate "nog te beoordelen" from already-reviewed
rows instead of flagging every deviation forever.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.test_pipeline_sources import (
    is_test_pipeline_source_reviewed, mark_test_pipeline_reviewed, record_test_pipeline_source,
)
from isala_ocr.training.webui import create_web_app

ORIGIN_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
RERUN_ID = "bbbbbbbbbbbbbbbbbbbbbbbb"


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    return app, workspace


def _write_output(workspace: Path, source_id: str, value: str) -> None:
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample({
        "sample_id": f"sample-{source_id}", "source_id": source_id, "profile": "cmr",
        "field_key": "field_a", "field_label": "Field A", "crop_path": "crops/x.png",
        "image_width": 8, "image_height": 8, "roi_x1": 0, "roi_y1": 0, "roi_x2": 4, "roi_y2": 4,
        "raw_ocr": value, "raw_confidence": 0.9, "raw_variant": "original",
        "extraction_method": "dynamic_ocr", "status": "pending",
    })
    root = workspace / "extracted_output"
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{source_id}.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "measurements": {"field_a": {"display_name": "Field A", "parsed_value": value, "raw_text": value}},
    }), encoding="utf-8")


def test_mark_reviewed_round_trips_through_the_json_marker(tmp_path: Path) -> None:
    _app(tmp_path)
    workspace = tmp_path / "workspace"

    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is False
    mark_test_pipeline_reviewed(workspace, RERUN_ID, True)
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is True
    mark_test_pipeline_reviewed(workspace, RERUN_ID, False)
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is False


def test_toggle_route_flips_state_and_compare_page_reflects_it(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _write_output(workspace, ORIGIN_ID, "12")
    _write_output(workspace, RERUN_ID, "13")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-1")

    client = app.test_client()
    compare_url = f"/test-pipeline/vergelijk/{RERUN_ID}"
    body = client.get(compare_url).get_data(as_text=True)
    assert "Nog te beoordelen" in body
    assert "Markeer als beoordeeld" in body

    response = client.post(
        f"/test-pipeline/beoordeeld/{RERUN_ID}", data={"reviewed": "1"},
        headers={"X-Test-Pipeline-Async": "1"},
    )
    assert response.get_json() == {"ok": True, "reviewed": True}
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is True

    body = client.get(compare_url).get_data(as_text=True)
    assert "Beoordeeld — geen actie nodig" in body
    assert "Markeer als nog te beoordelen" in body

    client.post(f"/test-pipeline/beoordeeld/{RERUN_ID}", data={"reviewed": "0"})
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is False


def test_list_distinguishes_reviewed_rows_from_outstanding_ones(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _write_output(workspace, ORIGIN_ID, "12")
    _write_output(workspace, RERUN_ID, "13")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-1")

    client = app.test_client()
    body = client.get("/test-pipeline").get_data(as_text=True)
    assert "1 nog te beoordelen" in body
    assert "✓ Beoordeeld" not in body

    mark_test_pipeline_reviewed(workspace, RERUN_ID, True)
    body = client.get("/test-pipeline").get_data(as_text=True)
    assert "nog te beoordelen" not in body
    assert "✓ Beoordeeld" in body


def test_forgetting_a_source_also_clears_its_reviewed_marker(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _write_output(workspace, ORIGIN_ID, "12")
    _write_output(workspace, RERUN_ID, "13")
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-1")
    mark_test_pipeline_reviewed(workspace, RERUN_ID, True)
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is True

    from isala_ocr.training.test_pipeline_sources import forget_test_pipeline_source

    forget_test_pipeline_source(workspace, RERUN_ID)
    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is False


def test_reviewed_marker_survives_a_fresh_record_call_for_another_source(tmp_path: Path) -> None:
    """A second proefpagina upload (``record_test_pipeline_source`` for a
    different source) must not wipe an already-reviewed source's marker --
    it used to, since the marker file is a single shared JSON document and
    an earlier version of ``record_test_pipeline_source`` rewrote it without
    carrying the ``reviewed_ids`` key forward.
    """
    workspace = tmp_path / "workspace"
    record_test_pipeline_source(workspace, RERUN_ID, origin_source_id=ORIGIN_ID, job_id="job-1")
    mark_test_pipeline_reviewed(workspace, RERUN_ID, True)

    record_test_pipeline_source(workspace, "cccccccccccccccccccccccc", origin_source_id="dddddddddddddddddddddddd")

    assert is_test_pipeline_source_reviewed(workspace, RERUN_ID) is True
