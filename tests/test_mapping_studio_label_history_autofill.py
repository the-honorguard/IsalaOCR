from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.label_history import (
    MINIMUM_SOURCES_FOR_AUTO_SUGGESTION,
    label_family_history,
    suggest_family_for_label,
)
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]


def _block(block_id: str, *, role: str, text: str, table_id: str, column_index: int) -> dict:
    x1 = 0 if column_index == 0 else 30
    return {
        "block_id": block_id,
        "block_type": "table_cell",
        "role": role,
        "text": text,
        "normalized_text": text.lower(),
        "confidence": 0.95,
        "x1": x1, "y1": 0, "x2": x1 + 20, "y2": 20,
        "line_index": 0,
        "sequence_index": 0,
        "table_id": table_id,
        "row_index": 0,
        "column_index": column_index,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, table_id: str) -> dict:
    return {
        "relation_id": relation_id,
        "label_block_id": label_block_id,
        "value_block_id": value_block_id,
        "unit_block_id": "",
        "relation_type": "table_cell",
        "confidence": 0.95,
        "rank": 1,
        "context_text": "",
        "table_id": table_id,
        "row_index": 0,
        "value_column_index": 1,
    }


def _seed_confirmed_source(
    database: TrainingDatabase, source_id: str, *, label_text: str, field_key: str,
) -> None:
    """One source with a single confirmed label -> field mapping."""
    table_id = f"table-{source_id}"
    label_block_id, value_block_id, relation_id = f"label-{source_id}", f"value-{source_id}", f"relation-{source_id}"
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": 2,
        },
        [
            _block(label_block_id, role="label", text=label_text, table_id=table_id, column_index=0),
            _block(value_block_id, role="value", text="12.3 ml", table_id=table_id, column_index=1),
        ],
        [_relation(relation_id, label_block_id=label_block_id, value_block_id=value_block_id, table_id=table_id)],
    )
    database.sync_relation_mappings(
        source_id, [{"relation_id": relation_id, "field_key": field_key, "notes": "label-first mapping"}]
    )


def _seed_unmapped_source(database: TrainingDatabase, source_id: str, *, label_text: str) -> str:
    """One source with a single, still-unconfirmed label. Returns its relation_id."""
    table_id = f"table-{source_id}"
    label_block_id, value_block_id, relation_id = f"label-{source_id}", f"value-{source_id}", f"relation-{source_id}"
    database.replace_generic_detection(
        {
            "source_id": source_id, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{source_id}.png", "detector_version": "test", "token_count": 2,
        },
        [
            _block(label_block_id, role="label", text=label_text, table_id=table_id, column_index=0),
            _block(value_block_id, role="value", text="45.6 ml", table_id=table_id, column_index=1),
        ],
        [_relation(relation_id, label_block_id=label_block_id, value_block_id=value_block_id, table_id=table_id)],
    )
    return relation_id


def _make_app(tmp_path: Path) -> tuple[object, TrainingDatabase]:
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app, database


def _render_get(app, source_id: str) -> str:
    """GET the studio page for ``source_id``, bypassing the primary-workflow
    sidebar gate (``enforce_primary_workflow_gate`` in webui.py): these tests
    seed only the Mapping-relevant tables directly and don't run the full
    upstream pipeline (panel setup, table review, ...) the gate otherwise
    requires before a plain GET on this route is let through.
    """
    with app.test_request_context(f"/mapping-labels/{source_id}"):
        return app.view_functions["label_mapping_studio"](source_id)


def test_recurring_label_is_preselected_once_confirmed_often_enough(tmp_path: Path) -> None:
    app, database = _make_app(tmp_path)
    for index in range(MINIMUM_SOURCES_FOR_AUTO_SUGGESTION):
        _seed_confirmed_source(
            database, f"hist-{index}", label_text="Ejectiefractie", field_key="lv_ejection_fraction",
        )
    relation_id = _seed_unmapped_source(database, "new-source", label_text="Ejectiefractie")

    body = _render_get(app, "new-source")

    assert f"Voorstel ({MINIMUM_SOURCES_FOR_AUTO_SUGGESTION}x)" in body
    # The option for the suggested family must actually carry `selected`.
    marker = f'value="family:ejection_fraction"'
    option_start = body.index(marker)
    option_tag = body[max(0, option_start - 200):option_start + len(marker) + 20]
    assert "selected" in option_tag
    # Nothing was written to the database yet - this is a pre-fill, not an auto-confirm.
    assert database.list_mappings("new-source", status="confirmed") == []
    assert relation_id  # sanity: fixture actually created a relation


def test_label_below_threshold_is_not_preselected(tmp_path: Path) -> None:
    app, database = _make_app(tmp_path)
    for index in range(MINIMUM_SOURCES_FOR_AUTO_SUGGESTION - 1):
        _seed_confirmed_source(
            database, f"hist-{index}", label_text="Ejectiefractie", field_key="lv_ejection_fraction",
        )
    _seed_unmapped_source(database, "new-source", label_text="Ejectiefractie")

    body = _render_get(app, "new-source")
    assert "automatisch voorgesteld" not in body
    assert "Voorstel (" not in body


def test_label_confirmed_to_two_different_families_is_not_preselected(tmp_path: Path) -> None:
    """A label that history disagrees on (two different field *families*, not
    just left/right of the same one) must stay a manual decision. Left/right
    of the same field (lv_es_volume/rv_es_volume) is a single family and is
    covered separately by
    ``test_label_family_history_aggregates_across_lateral_sides``.
    """
    app, database = _make_app(tmp_path)
    for index in range(MINIMUM_SOURCES_FOR_AUTO_SUGGESTION):
        _seed_confirmed_source(
            database, f"hist-ed-{index}", label_text="ED Volume", field_key="lv_ed_volume",
        )
    _seed_confirmed_source(database, "hist-density-outlier", label_text="ED Volume", field_key="lv_cardiac_density")
    _seed_unmapped_source(database, "new-source", label_text="ED Volume")

    body = _render_get(app, "new-source")
    assert "Voorstel (" not in body


def test_label_family_history_aggregates_across_lateral_sides() -> None:
    history_rows = [
        {"label_text": "ED Volume", "field_key": "lv_ed_volume", "source_count": 3},
        {"label_text": "ED Volume", "field_key": "rv_ed_volume", "source_count": 4},
        {"label_text": "Cardiac Density", "field_key": "lv_cardiac_density", "source_count": 2},
    ]
    fields = [
        {"field_key": "lv_ed_volume"}, {"field_key": "rv_ed_volume"}, {"field_key": "lv_cardiac_density"},
    ]
    history = label_family_history(history_rows, fields, field_family=lambda f: f["field_key"].split("_", 1)[1])
    assert history["ed volume"] == {"ed_volume": 7}
    assert history["cardiac density"] == {"cardiac_density": 2}


def test_suggest_family_for_label_requires_single_dominant_family() -> None:
    history = {"ed volume": {"ed_volume": 7}, "es volume": {"es_volume": 3, "ed_volume": 2}}
    assert suggest_family_for_label("ED Volume", history, minimum_sources=5) == ("ed_volume", 7)
    assert suggest_family_for_label("ES Volume", history, minimum_sources=1) is None
    assert suggest_family_for_label("Unknown Label", history) is None
