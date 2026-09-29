from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping import ensure_default_field_definitions
from isala_ocr.training.projects import resolve_project_workspace
from isala_ocr.training.table_semantics import save_assignment
from isala_ocr.training.webui import create_web_app

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ID = "queue-source"
TABLE_ID = "queue-table"


def _block(block_id: str, *, role: str, text: str, column_index: int, row_index: int) -> dict:
    x1 = 0 if column_index == 0 else 30
    return {
        "block_id": block_id, "block_type": "table_cell", "role": role, "text": text,
        "normalized_text": text.lower(), "confidence": 0.95,
        "x1": x1, "y1": row_index * 20, "x2": x1 + 20, "y2": row_index * 20 + 20,
        "line_index": row_index, "sequence_index": row_index,
        "table_id": TABLE_ID, "row_index": row_index, "column_index": column_index,
    }


def _relation(relation_id: str, *, label_block_id: str, value_block_id: str, row_index: int) -> dict:
    return {
        "relation_id": relation_id, "label_block_id": label_block_id, "value_block_id": value_block_id,
        "unit_block_id": "", "relation_type": "table_cell", "confidence": 0.95, "rank": 1,
        "context_text": "", "table_id": TABLE_ID, "row_index": row_index, "value_column_index": 1,
    }


def _make_app(tmp_path: Path):
    workspace = tmp_path / "training" / "workspace"
    project = tmp_path / "project"
    project.mkdir(parents=True)
    (project / "VERSION").write_text("3.16.0")
    resolved_workspace = resolve_project_workspace(workspace)
    database = TrainingDatabase(resolved_workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    rows = [
        ("Ejectiefractie", "lv-ef"), ("Cardiac Output", "lv-co"), ("ED Volume", "lv-ed"),
    ]
    blocks, relations = [], []
    for index, (label_text, tag) in enumerate(rows):
        label_id, value_id, relation_id = f"label-{tag}", f"value-{tag}", f"relation-{tag}"
        blocks.append(_block(label_id, role="label", text=label_text, column_index=0, row_index=index))
        blocks.append(_block(value_id, role="value", text="12.3", column_index=1, row_index=index))
        relations.append(_relation(relation_id, label_block_id=label_id, value_block_id=value_id, row_index=index))
    database.replace_generic_detection(
        {
            "source_id": SOURCE_ID, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{SOURCE_ID}.png", "detector_version": "test", "token_count": len(blocks),
        },
        blocks, relations,
    )
    # All fixtures in this file reuse the same TABLE_ID, so one Stap-6
    # semantic name resolves relation_lateral_side() for every source here
    # (main + history) to "left", making family -> field_key unambiguous.
    save_assignment(resolved_workspace, TABLE_ID, "Linker ventrikel")
    app = create_web_app(
        workspace, models_root=tmp_path / "models", output_root=tmp_path / "output", project_root=project,
    )
    return app, database


def _get_queue(app, source_id: str, relation_id: str) -> str:
    with app.test_request_context(f"/mapping-labels/{source_id}/queue/{relation_id}"):
        return app.view_functions["label_mapping_queue_item"](source_id, relation_id)


def _post_queue(app, source_id: str, relation_id: str, **form: str):
    with app.test_request_context(
        f"/mapping-labels/{source_id}/queue/{relation_id}", method="POST", data=form,
    ):
        return app.view_functions["label_mapping_queue_item"](source_id, relation_id)


def _start_queue(app, source_id: str):
    with app.test_request_context(f"/mapping-labels/{source_id}/queue"):
        return app.view_functions["label_mapping_queue_start"](source_id)


def test_queue_start_redirects_to_first_pending_relation(tmp_path: Path) -> None:
    app, _database = _make_app(tmp_path)
    response = _start_queue(app, SOURCE_ID)
    assert response.status_code == 302
    assert "/queue/relation-lv-ef" in response.headers["Location"]


def test_confirming_advances_to_next_pending_and_saves(tmp_path: Path) -> None:
    app, database = _make_app(tmp_path)

    body = _get_queue(app, SOURCE_ID, "relation-lv-ef")
    assert "Ejectiefractie" in body
    assert "label 1/3" in body

    response = _post_queue(
        app, SOURCE_ID, "relation-lv-ef",
        mapping_queue_action="confirm", field_choice="family:ejection_fraction",
    )
    assert response.status_code == 302
    assert "/queue/relation-lv-co" in response.headers["Location"]

    mappings = {item["field_key"]: item for item in database.list_mappings(SOURCE_ID, status="confirmed")}
    assert "lv_ejection_fraction" in mappings
    assert mappings["lv_ejection_fraction"]["relation_id"] == "relation-lv-ef"


def test_skip_action_ignores_dropdown_and_leaves_relation_unmapped(tmp_path: Path) -> None:
    app, database = _make_app(tmp_path)

    response = _post_queue(
        app, SOURCE_ID, "relation-lv-ef",
        mapping_queue_action="skip", field_choice="family:ejection_fraction",
    )
    assert response.status_code == 302
    assert "/queue/relation-lv-co" in response.headers["Location"]
    assert database.list_mappings(SOURCE_ID, status="confirmed") == []


def test_last_pending_confirmation_with_no_other_source_returns_to_index(tmp_path: Path) -> None:
    """With only one source in the project and nothing left pending anywhere,
    the queue must stop at the project-wide index, not loop back to this
    (now fully-mapped) source's own bulk page -- see
    test_queue_continues_into_the_next_source_once_this_one_is_done for the
    case where a next source *does* have open work."""
    app, _database = _make_app(tmp_path)
    for relation_id, family in (
        ("relation-lv-ef", "family:ejection_fraction"),
        ("relation-lv-co", "family:cardiac_output"),
    ):
        _post_queue(app, SOURCE_ID, relation_id, mapping_queue_action="confirm", field_choice=family)

    response = _post_queue(
        app, SOURCE_ID, "relation-lv-ed", mapping_queue_action="confirm", field_choice="family:ed_volume",
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/mapping-labels")


def test_queue_continues_into_the_next_source_once_this_one_is_done(tmp_path: Path) -> None:
    """The whole point of a queue: finishing one source's last label must
    jump straight into the next source's first open label, never back to a
    bulk page or the "Bron" picker."""
    app, database = _make_app(tmp_path)
    other_source = "other-source"
    database.replace_generic_detection(
        {
            "source_id": other_source, "image_width": 200, "image_height": 100,
            "render_path": f"source_renders/{other_source}.png", "detector_version": "test", "token_count": 2,
        },
        [
            _block(f"label-{other_source}", role="label", text="Cardiac Output", column_index=0, row_index=0),
            _block(f"value-{other_source}", role="value", text="5.0", column_index=1, row_index=0),
        ],
        [_relation(f"relation-{other_source}", label_block_id=f"label-{other_source}", value_block_id=f"value-{other_source}", row_index=0)],
    )
    # list_detection_sources() orders newest-detected-first; force other_source
    # to sort *after* SOURCE_ID regardless of wall-clock timing, so it is
    # actually in "the remaining sources" the queue continues into.
    with database.connect() as db:
        db.execute("UPDATE detection_sources SET detected_at='2000-01-01T00:00:00Z' WHERE source_id=?", (other_source,))

    for relation_id, family in (
        ("relation-lv-ef", "family:ejection_fraction"),
        ("relation-lv-co", "family:cardiac_output"),
    ):
        _post_queue(app, SOURCE_ID, relation_id, mapping_queue_action="confirm", field_choice=family)

    response = _post_queue(
        app, SOURCE_ID, "relation-lv-ed", mapping_queue_action="confirm", field_choice="family:ed_volume",
    )
    assert response.status_code == 302
    assert f"/mapping-labels/{other_source}/queue/relation-{other_source}" in response.headers["Location"]


def test_queue_item_preselects_history_based_suggestion(tmp_path: Path) -> None:
    """The queue must show the same auto-suggestion as the bulk page, not
    just a blank dropdown, so confirming it is a single keypress."""
    from isala_ocr.training.label_history import MINIMUM_SOURCES_FOR_AUTO_SUGGESTION

    app, database = _make_app(tmp_path)
    for index in range(MINIMUM_SOURCES_FOR_AUTO_SUGGESTION):
        other_source = f"hist-{index}"
        database.replace_generic_detection(
            {
                "source_id": other_source, "image_width": 200, "image_height": 100,
                "render_path": f"source_renders/{other_source}.png", "detector_version": "test", "token_count": 2,
            },
            [
                _block(f"label-{other_source}", role="label", text="ED Volume", column_index=0, row_index=0),
                _block(f"value-{other_source}", role="value", text="9.9", column_index=1, row_index=0),
            ],
            [_relation(f"relation-{other_source}", label_block_id=f"label-{other_source}", value_block_id=f"value-{other_source}", row_index=0)],
        )
        database.sync_relation_mappings(
            other_source, [{"relation_id": f"relation-{other_source}", "field_key": "lv_ed_volume", "notes": "label-first mapping"}]
        )

    body = _get_queue(app, SOURCE_ID, "relation-lv-ed")
    marker = 'value="family:ed_volume"'
    option_start = body.index(marker)
    assert "selected" in body[option_start:option_start + 60]
