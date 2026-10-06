"""The proefpagina list (/test-pipeline) flags a "getest" row whose datablok
differs from its trainingspipeline origin, using the exact same field-by-field
rule the compare screen's STAP 7 uses (``_measurement_diff_rows``, shared),
so a deviation is visible without opening every row's compare screen. Also
covers the "Geselecteerd opnieuw testen" bulk-rerun button's presence and
basic reachability.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.webui import create_web_app

ORIGIN_ID = "aaaaaaaaaaaaaaaaaaaaaaaa"
RERUN_DIFFERS_ID = "bbbbbbbbbbbbbbbbbbbbbbbb"
ORIGIN_MATCH_ID = "cccccccccccccccccccccccc"
RERUN_MATCHES_ID = "dddddddddddddddddddddddd"


def _app(tmp_path: Path):
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    (project_root / "VERSION").write_text("3.9.7", encoding="utf-8")
    base = tmp_path / "training" / "workspace"
    app = create_web_app(base, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project_root)
    workspace = base / "projects" / "cmr_testcase_01"
    return app, workspace


def _write_output(workspace: Path, source_id: str, value: str) -> None:
    # An assessable /test-pipeline row is only listed once source_rows()
    # (backed by the samples table) knows about the source_id -- an
    # extracted_output file alone is not enough, the same requirement the
    # real training pipeline always satisfies for a source it assessed.
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


def test_list_flags_a_tested_row_whose_datablok_differs(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source

    _write_output(workspace, ORIGIN_ID, "12")
    _write_output(workspace, RERUN_DIFFERS_ID, "13")
    record_test_pipeline_source(workspace, RERUN_DIFFERS_ID, origin_source_id=ORIGIN_ID, job_id="job-1")

    body = app.test_client().get("/test-pipeline").get_data(as_text=True)
    assert "1 verschil" in body, "differing field_a (12 vs 13) should surface as a deviation alert"
    assert "Getraind" in body, "a source with extracted_output must be marked trained"


def test_list_shows_gelijk_when_datablok_matches(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source

    _write_output(workspace, ORIGIN_MATCH_ID, "12")
    _write_output(workspace, RERUN_MATCHES_ID, "12")
    record_test_pipeline_source(workspace, RERUN_MATCHES_ID, origin_source_id=ORIGIN_MATCH_ID, job_id="job-2")

    body = app.test_client().get("/test-pipeline").get_data(as_text=True)
    assert "Gelijk" in body
    assert "⚠" not in body, "no deviation alert should render when the datablok matches"


def test_bulk_retest_button_and_route_present_when_rows_exist(tmp_path: Path) -> None:
    app, workspace = _app(tmp_path)
    _write_output(workspace, ORIGIN_ID, "12")

    body = app.test_client().get("/test-pipeline").get_data(as_text=True)
    assert "Geselecteerd opnieuw testen" in body
    assert "test_pipeline_rerun_selected" in app.view_functions

    response = app.test_client().post(
        "/test-pipeline/geselecteerd-opnieuw-testen", data={"source_ids": [ORIGIN_ID]}, follow_redirects=True,
    )
    assert response.status_code == 200


def test_no_bulk_retest_button_when_list_is_empty(tmp_path: Path) -> None:
    app, _workspace = _app(tmp_path)
    body = app.test_client().get("/test-pipeline").get_data(as_text=True)
    # The phrase itself also appears in an explanatory JS comment that's
    # always present, so this checks for the button element specifically.
    assert 'class="button primary js-bulk-retest"' not in body


def test_untrained_but_tested_row_never_shows_gelijk(tmp_path: Path) -> None:
    """"Gelijk" means this run's datablok matches the trainingspipeline's own
    -- it can never be true for a "Nog niet getraind" origin, since there is
    no trainingspipeline datablok at all to compare against.
    ``_measurement_diff_rows`` returns ``[]`` (nothing differs) whenever
    either side has no datablok yet, which used to make an untrained-but-
    tested row's ``differing_count`` land on 0 -- the exact same value a
    genuine match produces -- and the template couldn't tell the two apart.
    """
    from flask import render_template

    app, _workspace = _app(tmp_path)
    rows = [{
        "source_id": "untrained-source", "render_exists": False, "trained": False,
        "rerun_source_id": "rerun-1", "status": "tested",
        "compare_url": "/test-pipeline/vergelijk/rerun-1",
        "running_job_id": None, "differing_count": 0,
    }]
    with app.test_request_context():
        html = render_template("test_pipeline.html", rows=rows, rerun_error="", running_job_ids=[])

    assert "Nog niet vergelijkbaar" in html
    assert "Gelijk" not in html
