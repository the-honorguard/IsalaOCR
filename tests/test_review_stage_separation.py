from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.projects import ProjectManager
from isala_ocr.training.webui import create_web_app


def sample(sample_id: str, field_key: str, raw_ocr: str) -> dict:
    return {
        "sample_id": sample_id,
        "source_id": "dicom-1",
        "profile": "profile",
        "field_key": field_key,
        "field_label": f"Field {field_key}",
        "crop_path": f"crops/{sample_id}.png",
        "raw_ocr": raw_ocr,
        "raw_confidence": 0.99,
        "raw_variant": "test",
        "image_width": 100,
        "image_height": 100,
        "roi_x1": 1,
        "roi_y1": 2,
        "roi_x2": 50,
        "roi_y2": 20,
        "extraction_method": "mapped_generic",
        "locator_confidence": 0.95,
        "locator_label_text": field_key,
        "locator_version": "test",
        "crop_sha256": sample_id,
    }


def make_app(tmp_path: Path):
    workspace = tmp_path / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample(sample("approved", "approved", "VISIBLE_APPROVED"))
    database.upsert_sample(sample("waiting", "waiting", "HIDDEN_PENDING"))
    database.review_roi("approved", "correct")
    project = tmp_path / "project"
    project.mkdir()
    (project / "VERSION").write_text("3.5.14", encoding="utf-8")
    app = create_web_app(
        workspace,
        models_root=tmp_path / "models",
        output_root=tmp_path / "output",
        project_root=project,
    )
    # create_web_app migrates a bare workspace into
    # workspace/projects/<project-id>/samples.sqlite3 via ProjectManager, so the
    # pre-migration `database` handle above no longer points at the file the
    # app's routes read/write. Reopen it at the migrated path.
    project_manager = ProjectManager(workspace)
    migrated_database = TrainingDatabase(project_manager.active_workspace() / "samples.sqlite3")
    return app, migrated_database


def test_roi_page_contains_no_ocr_value_content(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    response = app.test_client().get("/roi-review/dicom-1")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "VISIBLE_APPROVED" not in text
    assert "HIDDEN_PENDING" not in text
    assert "Exact zichtbare tekst" not in text
    assert "ROI klopt" in text
    assert "ROI fout" in text


def test_value_pages_show_only_roi_approved_samples(tmp_path: Path) -> None:
    app, _ = make_app(tmp_path)
    client = app.test_client()

    # /review is now a bare redirect into the unified process-step page for the
    # value-review step; it no longer renders a document overview itself.
    overview = client.get("/review")
    assert overview.status_code == 302
    assert overview.headers["Location"] == "/process/value-review"

    # The legacy per-document review page still works, but only when explicitly
    # requested with ?legacy=1 - otherwise it also redirects to /process/value-review.
    document = client.get("/review/document/dicom-1?legacy=1").get_data(as_text=True)
    assert "VISIBLE_APPROVED" in document
    assert "Field approved" in document
    assert "HIDDEN_PENDING" not in document
    assert "Field waiting" not in document
    assert "ROI/extractie fout" not in document
    assert "locator" not in document.lower()

    queue = client.get("/review/queue?status=pending").get_data(as_text=True)
    assert "VISIBLE_APPROVED" in queue
    assert "HIDDEN_PENDING" not in queue
    assert "Extractiemethode" not in queue


def test_marking_roi_incorrect_invalidates_existing_value_review(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(sample("approved", "approved", "123"))
    database.review_roi("approved", "correct")
    database.review("approved", "accepted", "123", "checked")

    database.review_roi("approved", "incorrect", "wrong row")
    stored = database.get("approved")
    assert stored is not None
    assert stored["roi_review_status"] == "incorrect"
    assert stored["roi_review_notes"] == "wrong row"
    assert stored["status"] == "pending"
    assert stored["exact_label"] is None
    assert database.accepted() == []

    with database.connect() as db:
        reason = db.execute(
            "SELECT reason FROM review_history WHERE sample_id='approved' ORDER BY history_id DESC"
        ).fetchone()[0]
    assert reason == "roi_review_changed_to_incorrect"


def test_only_roi_approved_values_are_training_candidates(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(sample("approved", "approved", "123"))
    database.upsert_sample(sample("waiting", "waiting", "456"))
    database.review("approved", "accepted", "123")
    database.review("waiting", "accepted", "456")
    database.review_roi("approved", "correct")

    accepted = database.accepted()
    assert [item["sample_id"] for item in accepted] == ["approved"]


def test_legacy_value_roi_error_moves_to_roi_review(tmp_path: Path) -> None:
    path = tmp_path / "samples.sqlite3"
    database = TrainingDatabase(path)
    database.upsert_sample(sample("legacy", "legacy", "wrong crop"))
    with database.connect() as db:
        db.execute(
            "UPDATE samples SET status='roi_error', notes='wrong row', reviewed_at='2026-08-06T00:00:00+00:00' WHERE sample_id='legacy'"
        )
        db.execute("UPDATE metadata SET value='5' WHERE key='schema_version'")
        db.execute("PRAGMA user_version=5")

    migrated = TrainingDatabase(path)
    stored = migrated.get("legacy")
    assert stored is not None
    assert stored["roi_review_status"] == "incorrect"
    assert stored["roi_review_notes"] == "wrong row"
    assert stored["status"] == "pending"
    assert stored["notes"] == ""


def test_deferred_roi_is_preserved_separately_from_unreviewed_default_ok(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(sample("deferred", "deferred", "123"))
    database.review_roi("deferred", "deferred", "review later")

    stored = database.get("deferred")
    assert stored is not None
    assert stored["roi_review_status"] == "deferred"
    assert stored["roi_review_notes"] == "review later"
    assert stored["roi_reviewed_at"] is not None



def test_deferred_roi_has_its_own_filter_and_is_not_in_value_review(tmp_path: Path) -> None:
    app, database = make_app(tmp_path)
    database.review_roi("waiting", "deferred", "later")
    client = app.test_client()

    roi_page = client.get("/roi-review?status=deferred")
    assert roi_page.status_code == 200
    roi_text = roi_page.get_data(as_text=True)
    assert "Later beoordelen" in roi_text
    assert "dicom-1" in roi_text

    value_text = client.get("/review/document/dicom-1?legacy=1").get_data(as_text=True)
    assert "HIDDEN_PENDING" not in value_text

