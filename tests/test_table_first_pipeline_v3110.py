from __future__ import annotations

from pathlib import Path

import yaml

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.table_quality import table_first_quality

ROOT = Path(__file__).resolve().parents[1]


def _seed_table_candidates(db: TrainingDatabase, source_id: str = "source-a", count: int = 10) -> None:
    candidates = []
    for index in range(count):
        x1 = 10 + (index % 2) * 120
        y1 = 10 + (index // 2) * 30
        candidates.append(
            {
                "candidate_id": f"cell-{index}",
                "source_id": source_id,
                "confidence": 0.90,
                "source_kind": "table_cell",
                "source_refs": [f"table:t:cell:{index}"],
                "crop_path": "",
                "x1": x1,
                "y1": y1,
                "x2": x1 + 100,
                "y2": y1 + 22,
            }
        )
    db.replace_localization_detection(
        {
            "source_id": source_id,
            "image_width": 300,
            "image_height": 220,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "ppstructure-table-v1",
            "token_count": 0,
        },
        candidates,
        [],
    )


def test_default_config_uses_table_first_without_field_detector_fusion() -> None:
    config = yaml.safe_load((ROOT / "application/config/app.yaml").read_text(encoding="utf-8"))
    localization = config["training"]["localization"]
    assert localization["strategy"] == "table_first"
    assert localization["table_first"]["enable_active_field_detector_fallback"] is False
    assert localization["table_first"]["include_broad_cells"] is True

    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert 'if table_first:' in collector
    assert 'candidates = list(cell_candidates)' in collector
    assert 'text_candidate_count = 0' in collector

    host_action = (ROOT / "automation/powershell/collect-training-data.ps1").read_text(encoding="utf-8")
    assert "Active field detector intentionally NOT merged" in host_action


def test_table_first_workflow_parks_the_old_detector() -> None:
    webui = (ROOT / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    assert '"key": "panel-setup","index":2,"group":"detection"' in webui
    assert '"key": "table-quality","index":5,"group":"detection"' in webui
    assert '"key": "table-model","index":6,"group":"detection"' in webui
    assert '"key": "table-compare","index":7,"group":"detection"' in webui
    assert '"key": "mapping","index":8,"group":"value"' in webui
    assert '"key": "localization-dataset","index":None,"group":"fallback"' in webui
    assert '"key": "localization-evaluate","index":None,"group":"fallback"' in webui

    base = (ROOT / "application/src/isala_ocr/training/templates/base.html").read_text(encoding="utf-8")
    assert "TABLE DETECTIE & CROPS" in base
    assert "GEPARKEERD · BOX DETECTOR" in base
    assert "pipeline_gate_global.gate_label" in base

    dockerfile = (ROOT / "infrastructure/docker/Dockerfile.labeler").read_text(encoding="utf-8")
    assert "training/table_quality.py" in dockerfile


def test_table_quality_passes_when_ppstructure_supplies_all_desired_cells(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_table_candidates(db)
    for index in range(10):
        db.review_detection_candidate(
            source_id="source-a", candidate_id=f"cell-{index}", review_status="correct"
        )

    db.set_detection_source_review_completed("source-a", True)
    result = table_first_quality(db)
    assert result["ready"] is True
    assert result["state"] == "table_only_sufficient"
    assert result["totals"]["direct_coverage"] == 1.0
    assert result["totals"]["fallback_need"] == 0.0
    assert result["totals"]["false_candidate_rate"] == 0.0


def test_table_quality_exposes_manual_fallback_need_instead_of_calling_it_success(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_table_candidates(db)
    for index in range(8):
        db.review_detection_candidate(
            source_id="source-a", candidate_id=f"cell-{index}", review_status="correct"
        )
    db.review_detection_candidate(
        source_id="source-a", candidate_id="cell-8", review_status="adjusted",
        corrected_box=(128, 130, 238, 154),
    )
    db.review_detection_candidate(
        source_id="source-a", candidate_id="cell-9", review_status="rejected",
        reason_code="false_positive",
    )
    db.add_detection_annotation(source_id="source-a", box=(10, 170, 110, 192))
    db.add_detection_annotation(source_id="source-a", box=(130, 170, 230, 192))
    db.set_detection_source_review_completed("source-a", True)

    result = table_first_quality(db)
    totals = result["totals"]
    assert totals["candidate_total"] == 10
    assert totals["detected_desired"] == 9
    assert totals["desired_total"] == 11
    assert totals["added"] == 2
    assert round(totals["direct_coverage"], 3) == 0.818
    assert round(totals["fallback_need"], 3) == 0.182
    assert result["ready"] is False
    assert result["state"] == "fallback_needed"


def test_mapping_runtime_checks_table_quality_in_table_first_mode() -> None:
    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert 'if strategy == "table_first":' in collector
    assert "table_first_quality(" in collector
    assert "TABLE-FIRST CHECK is closed" in collector


def test_table_quality_ignores_manual_boxes_from_an_older_detector_pass(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_table_candidates(db, count=1)
    db.review_detection_candidate(source_id="source-a", candidate_id="cell-0", review_status="correct")
    db.add_detection_annotation(source_id="source-a", box=(10, 60, 110, 82))

    # A fresh Step-2 pass defines a new table-first measurement session. The old
    # manual box is preserved in SQLite but must not count as a table-cell miss in
    # the fresh pass.
    _seed_table_candidates(db, count=1)
    db.review_detection_candidate(source_id="source-a", candidate_id="cell-0", review_status="correct")
    db.set_detection_source_review_completed("source-a", True)

    result = table_first_quality(db)
    assert result["totals"]["added"] == 0
    assert result["totals"]["direct_coverage"] == 1.0


def test_table_first_collector_skips_separate_full_page_ocr_geometry() -> None:
    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    assert "if not table_first:\n        locator_engine.warmup()" in collector
    assert "if table_first:\n                tokens = []" in collector
    assert '"reason": "table_first_geometry_only"' in collector


def test_table_quality_requires_explicit_source_completion_to_expose_missing_cells(tmp_path: Path) -> None:
    db = TrainingDatabase(tmp_path / "samples.sqlite3")
    _seed_table_candidates(db, count=2)
    for index in range(2):
        db.review_detection_candidate(source_id="source-a", candidate_id=f"cell-{index}", review_status="correct")

    result = table_first_quality(db)
    assert result["ready"] is False
    assert result["state"] == "needs_review"
    assert result["incomplete_sources"] == 1
    assert "Afbeelding klaar" in result["next_step"]
