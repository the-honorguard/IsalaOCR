from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.table_cell_ground_truth import ground_truth_path
from isala_ocr.training.test_pipeline_sources import record_test_pipeline_source
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SOURCE = "canonical-gt-source"
UNREVIEWED_SOURCE = "unreviewed-detection-source"
PROEFPAGINA_SOURCE = "proefpagina-source"


def _seed_source(database: TrainingDatabase, source_id: str) -> None:
    table_id = f"table-{source_id}"
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": 2,
        },
        [
            {
                "block_id": f"label-{source_id}", "block_type": "table_cell", "role": "label",
                "text": "Ejectiefractie", "normalized_text": "ejectiefractie", "confidence": 0.95,
                "x1": 0, "y1": 0, "x2": 20, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 0,
            },
            {
                "block_id": f"value-{source_id}", "block_type": "table_cell", "role": "value",
                "text": "40 %", "normalized_text": "40 %", "confidence": 0.95,
                "x1": 30, "y1": 0, "x2": 50, "y2": 20, "line_index": 0, "sequence_index": 0,
                "table_id": table_id, "row_index": 0, "column_index": 1,
            },
        ],
        [{
            "relation_id": f"relation-{source_id}", "label_block_id": f"label-{source_id}",
            "value_block_id": f"value-{source_id}", "unit_block_id": "", "relation_type": "table_cell",
            "confidence": 0.95, "rank": 1, "context_text": "", "table_id": table_id,
            "row_index": 0, "value_column_index": 1,
        }],
    )


def _write_canonical_gt(workspace: Path, *source_ids: str) -> None:
    ground_truth_path(workspace).parent.mkdir(parents=True, exist_ok=True)
    ground_truth_path(workspace).write_text(json.dumps({
        "schema_version": 1,
        "type": "canonical_table_cell_ground_truth",
        "base_dataset_id": "dataset-v1",
        "base_review_fingerprint": "abc",
        "created_at": "2026-08-14T10:00:00+00:00",
        "updated_at": "2026-08-14T10:00:00+00:00",
        "revision": 1,
        "sources": {
            source_id: {
                "source_id": source_id, "split": "train",
                "cells": [{"gt_id": f"gt-{source_id}", "source_id": source_id, "x1": 10, "y1": 10, "x2": 40, "y2": 30}],
            }
            for source_id in source_ids
        },
    }), encoding="utf-8")


def _make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    for source_id in (CANONICAL_SOURCE, UNREVIEWED_SOURCE, PROEFPAGINA_SOURCE):
        _seed_source(database, source_id)
    record_test_pipeline_source(resolved_workspace, PROEFPAGINA_SOURCE, origin_source_id=CANONICAL_SOURCE)
    # Only CANONICAL_SOURCE was ever promoted to canonical GT in Stap 5's GT
    # Studio; UNREVIEWED_SOURCE reproduces the real report's other gap: a
    # source with real, automatically-detected relations that nobody ever
    # curated, still showing up in Mapping Studio's list alongside the ~30
    # sources an operator actually reviewed.
    _write_canonical_gt(resolved_workspace, CANONICAL_SOURCE)

    # config_path must resolve to the real app.yaml (strategy: table_first)
    # for canonical_table_gt_mode() to ever be true; create_web_app()'s own
    # default points at a container-only absolute path.
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
        config_path=ROOT / "application" / "config" / "app.yaml",
    )
    return app, database, resolved_workspace


def test_bulk_page_only_lists_canonical_gt_sources(tmp_path: Path) -> None:
    app, _database, _workspace = _make_app(tmp_path)
    with app.test_request_context(f"/mapping-labels/{CANONICAL_SOURCE}"):
        body = app.view_functions["label_mapping_studio"](CANONICAL_SOURCE)
    assert f'value="{CANONICAL_SOURCE}"' in body
    assert f'value="{UNREVIEWED_SOURCE}"' not in body
    assert f'value="{PROEFPAGINA_SOURCE}"' not in body


def test_global_queue_never_lands_on_an_unreviewed_or_proefpagina_source(tmp_path: Path) -> None:
    app, _database, _workspace = _make_app(tmp_path)
    with app.test_request_context("/mapping-labels/queue"):
        response = app.view_functions["label_mapping_queue_global_start"]()
    assert response.status_code == 302
    assert f"/mapping-labels/{CANONICAL_SOURCE}/queue/" in response.headers["Location"]
