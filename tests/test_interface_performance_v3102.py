from __future__ import annotations

from pathlib import Path

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.projects import ProjectManager

ROOT = Path(__file__).resolve().parents[1]


def _candidate(source_id: str, candidate_id: str, x: int) -> dict:
    return {
        "candidate_id": candidate_id,
        "source_id": source_id,
        "confidence": 0.9,
        "source_kind": "text_geometry",
        "source_refs": [],
        "crop_path": "",
        "x1": x,
        "y1": 10,
        "x2": x + 30,
        "y2": 35,
    }


def test_project_metadata_is_reused_while_files_are_unchanged(tmp_path: Path, monkeypatch) -> None:
    manager = ProjectManager(tmp_path / "workspace")
    calls: list[str] = []
    original = manager._read_json

    def counted(path: Path, default):
        calls.append(path.name)
        return original(path, default)

    monkeypatch.setattr(manager, "_read_json", counted)
    for _ in range(20):
        assert manager.active_project_id()
        assert manager.active().project_id
        assert manager.list_projects()

    assert "projects.json" not in calls
    assert "active_project.json" not in calls


def test_bulk_detection_review_counts_match_per_source_counts(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    for index, source_id in enumerate(("a", "b")):
        source = {
            "source_id": source_id,
            "image_width": 320,
            "image_height": 120,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "test",
            "token_count": 0,
        }
        db.replace_localization_detection(
            source,
            [
                _candidate(source_id, f"{source_id}-ok", 10),
                _candidate(source_id, f"{source_id}-bad", 80),
                _candidate(source_id, f"{source_id}-open", 150),
            ],
            [],
        )
        db.review_detection_candidate(
            source_id=source_id,
            candidate_id=f"{source_id}-ok",
            review_status="correct",
        )
        db.review_detection_candidate(
            source_id=source_id,
            candidate_id=f"{source_id}-bad",
            review_status="rejected",
            reason_code="false_positive",
        )
        if index == 1:
            db.add_detection_annotation(source_id=source_id, box=(210, 20, 270, 50))

    grouped = db.detection_review_counts_by_source()
    assert grouped["a"] == db.detection_review_counts("a")
    assert grouped["b"] == db.detection_review_counts("b")


def test_reactive_clients_use_adaptive_polling() -> None:
    expectations = {
        "localization-workbench.ts": ("2500", "12000"),
        "localization-quality.ts": ("2500", "12000"),
        "localization-artifacts.ts": ("3000", "15000"),
    }
    for name, (active_delay, idle_delay) in expectations.items():
        source = (ROOT / "frontend" / "src" / name).read_text(encoding="utf-8")
        assert "window.setInterval" not in source
        assert "window.setTimeout" in source
        assert active_delay in source
        assert idle_delay in source
        assert "document.hidden ? 30000" in source


def test_global_status_polling_is_adaptive_and_idle_is_slower() -> None:
    source = (ROOT / "application/src/isala_ocr/training/static/app.js").read_text(encoding="utf-8")
    assert "setInterval(pollStatus" not in source
    assert "schedulePoll" in source
    assert "document.hidden ? 30000" in source
    assert "hasLiveJobs ? 2000 : 10000" in source


def test_large_review_images_are_lazy_or_async_decoded() -> None:
    templates = ROOT / "application/src/isala_ocr/training/templates"
    review = (templates / "review_document.html").read_text(encoding="utf-8")
    mapping = (templates / "mapping_studio.html").read_text(encoding="utf-8")
    detection = (templates / "detection_review_studio.html").read_text(encoding="utf-8")
    assert 'loading="lazy" decoding="async"' in review
    assert mapping.count('loading="lazy" decoding="async"') >= 2
    assert 'fetchpriority="high"' in detection
    assert 'loading="lazy" decoding="async"' in detection


def test_mapping_roi_resolution_reuses_preloaded_geometry() -> None:
    from isala_ocr.training.mapping import resolve_value_roi_box

    class NoQueryDatabase:
        def get_detected_block(self, _value_block_id: str):
            raise AssertionError("block should be preloaded")

        def list_detection_annotations(self, _source_id: str, active_only: bool = True):
            raise AssertionError("annotations should be preloaded")

        def list_detection_candidates(self, _source_id: str):
            raise AssertionError("candidates should be preloaded")

    block = {
        "block_id": "value-1",
        "source_id": "source-1",
        "role": "value",
        "x1": 42,
        "y1": 22,
        "x2": 88,
        "y2": 48,
    }
    annotations = [
        {
            "annotation_id": "annotation-1",
            "source_id": "source-1",
            "x1": 38,
            "y1": 18,
            "x2": 94,
            "y2": 54,
            "review_status": "correct",
            "provenance": "manual",
        }
    ]

    box, diagnostics = resolve_value_roi_box(
        NoQueryDatabase(),
        "value-1",
        200,
        100,
        block=block,
        annotations=annotations,
        candidates=[],
    )

    assert box.to_list() == [38, 18, 94, 54]
    assert diagnostics["geometry_source"] == "pipeline_a_reviewed_annotation"
