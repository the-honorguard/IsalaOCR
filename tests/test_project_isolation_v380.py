from __future__ import annotations

import json
import os
from pathlib import Path

import cv2
import numpy as np

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.localization_dataset import build_localization_dataset, localization_dataset_preview
from isala_ocr.training.projects import (
    DEFAULT_PROJECT_ID,
    ProjectManager,
    resolve_project_workspace,
)

ROOT = Path(__file__).resolve().parents[1]


def _candidate(cid: str, x: int) -> dict:
    return {
        "candidate_id": cid, "source_id": "s", "confidence": 0.9,
        "source_kind": "text_geometry", "source_refs": [], "crop_path": "",
        "x1": x, "y1": 10, "x2": x + 30, "y2": 30,
    }


def _seed_source(workspace: Path) -> TrainingDatabase:
    db = TrainingDatabase(workspace / "samples.sqlite3")
    render = workspace / "source_renders" / "s.png"
    render.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(render), np.zeros((80, 160, 3), dtype=np.uint8))
    source = {"source_id": "s", "image_width": 160, "image_height": 80,
              "render_path": "source_renders/s.png", "detector_version": "test", "token_count": 0}
    db.replace_localization_detection(source, [_candidate("positive", 10), _candidate("negative", 80), _candidate("open", 120)], [])
    return db


def test_legacy_workspace_migrates_once_into_default_project(tmp_path: Path) -> None:
    base = tmp_path / "training" / "workspace"
    base.mkdir(parents=True)
    legacy = TrainingDatabase(base / "samples.sqlite3")
    with legacy.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", ("legacy_marker", "present"))
    manager = ProjectManager(base)
    active = manager.active()
    assert active.project_id == DEFAULT_PROJECT_ID
    assert (active.workspace / "samples.sqlite3").is_file()
    assert not (base / "samples.sqlite3").exists()
    migrated = TrainingDatabase(active.workspace / "samples.sqlite3")
    with migrated.connect() as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key=?", ("legacy_marker",)).fetchone()[0] == "present"


def test_switching_projects_isolates_database_and_gate(tmp_path: Path) -> None:
    base = tmp_path / "training" / "workspace"
    manager = ProjectManager(base)
    first = manager.active()
    first_db = TrainingDatabase(first.workspace / "samples.sqlite3")
    first_db.set_detection_gate(True, reason="first")
    second = manager.create(name="Andere usecase", use_case_id="generic_document")
    second_db = TrainingDatabase(second.workspace / "samples.sqlite3")
    assert second_db.detection_gate()["ready"] is False
    with second_db.connect() as conn:
        conn.execute("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", ("only_second", "yes"))
    manager.switch(first.project_id)
    with TrainingDatabase(manager.active_workspace() / "samples.sqlite3").connect() as conn:
        assert conn.execute("SELECT value FROM metadata WHERE key=?", ("only_second",)).fetchone() is None
    assert TrainingDatabase(manager.active_workspace() / "samples.sqlite3").detection_gate()["ready"] is True


def test_environment_pins_background_job_to_queued_project(tmp_path: Path, monkeypatch) -> None:
    base = tmp_path / "training" / "workspace"
    manager = ProjectManager(base)
    first = manager.active()
    second = manager.create(name="Second", use_case_id="generic_document")
    manager.switch(second.project_id)
    monkeypatch.setenv("ISALA_PROJECT_ID", first.project_id)
    try:
        assert resolve_project_workspace(base) == first.workspace
    finally:
        monkeypatch.delenv("ISALA_PROJECT_ID", raising=False)


def test_incomplete_source_is_excluded_until_image_is_finished(tmp_path: Path) -> None:
    workspace = tmp_path / "standalone"
    db = _seed_source(workspace)
    db.review_detection_candidate(source_id="s", candidate_id="positive", review_status="correct")
    db.review_detection_candidate(source_id="s", candidate_id="negative", review_status="correct", relevance_status="irrelevant")
    preview = localization_dataset_preview(workspace)
    assert preview["totals"]["ready_sources"] == 0
    assert preview["sources"][0]["pending"] == 1
    assert preview["sources"][0]["included"] is False

    db.set_detection_source_review_completed("s", True, accept_unreviewed=True)
    manifest = build_localization_dataset(workspace)
    assert manifest["positive_review_count"] == 2  # explicit positive + default-included open ROI
    assert manifest["negative_review_count"] == 1
    assert manifest["full_source_image_count"] == 1
    assert manifest["review_patch_image_count"] == 0
    assert manifest["negative_image_count"] == 0
    assert manifest["eligible_source_count"] == 1


def test_project_selector_and_worker_project_pin_are_present() -> None:
    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    projects = (ROOT / "application/src/isala_ocr/training/templates/projects.html").read_text(encoding="utf-8")
    worker = (ROOT / "automation/powershell/webui-worker.ps1").read_text(encoding="utf-8")
    compose = (ROOT / "infrastructure/docker/compose.yaml").read_text(encoding="utf-8")
    assert 'id="project-switch-select"' in base
    assert "Nieuw project" in projects and "Dupliceer" in projects
    assert 'set "ISALA_PROJECT_ID={0}"' in worker
    assert "ISALA_PROJECT_ID: ${ISALA_PROJECT_ID:-}" in compose


def test_new_project_gets_isolated_input_path_and_duplicate_keeps_use_case(tmp_path: Path) -> None:
    base = tmp_path / "training" / "workspace"
    manager = ProjectManager(base)
    generic = manager.create(name="Formulier pilot", use_case_id="generic_document")
    assert generic.input_path == f"/input/projects/{generic.project_id}"
    duplicate = manager.create(
        name="Formulier pilot kopie",
        use_case_id="generic_document",
        duplicate_from=generic.project_id,
    )
    assert duplicate.use_case_id == "generic_document"
    assert duplicate.input_path == generic.input_path


def test_duplicate_cannot_silently_change_use_case(tmp_path: Path) -> None:
    base = tmp_path / "training" / "workspace"
    manager = ProjectManager(base)
    source = manager.create(name="Bron", use_case_id="generic_document")
    try:
        manager.create(
            name="Foute kopie",
            use_case_id="philips_cmr_volume_results",
            duplicate_from=source.project_id,
        )
    except ValueError as exc:
        assert "dezelfde use-case" in str(exc)
    else:
        raise AssertionError("Cross-use-case project duplication should be rejected")


def test_use_case_templates_are_discovered_from_config() -> None:
    from isala_ocr.training.projects import load_use_case_templates

    templates = load_use_case_templates(ROOT / "application/config")
    ids = {item["use_case_id"] for item in templates}
    assert "philips_cmr_volume_results" in ids
    assert "generic_document" in ids


def test_project_specific_registry_path_is_not_nested_twice(tmp_path: Path) -> None:
    from isala_ocr.training.projects import resolve_project_registry

    base = tmp_path / "training" / "workspace"
    manager = ProjectManager(base)
    project = manager.active()
    registry = tmp_path / "training" / "registry" / "projects" / project.project_id
    resolved = resolve_project_registry(registry, project.workspace)
    assert resolved == registry.resolve()
    assert "projects" not in resolved.relative_to(registry).parts


def test_project_input_path_is_used_by_detection_and_mapping_actions() -> None:
    common = (ROOT / "automation/powershell/training-common.ps1").read_text(encoding="utf-8")
    collect = (ROOT / "automation/powershell/collect-training-data.ps1").read_text(encoding="utf-8")
    redetect = (ROOT / "automation/powershell/redetect-localization.ps1").read_text(encoding="utf-8")
    mapping = (ROOT / "automation/powershell/prepare-mapping-data.ps1").read_text(encoding="utf-8")
    assert "function Get-IsalaContainerProjectInput" in common
    assert "Get-IsalaContainerProjectInput" in collect
    assert "collect-training --input $ProjectInput" in redetect
    assert '"--input",$ProjectInput' in mapping
