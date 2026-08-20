from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "application/src/isala_ocr/mapping_gt_cli.py"
COLLECTOR = ROOT / "application/src/isala_ocr/training/mapping_ground_truth_fast.py"
SUGGESTIONS = ROOT / "application/src/isala_ocr/training/mapping_fast.py"


def test_canonical_mapping_uses_fast_collector() -> None:
    cli = CLI.read_text(encoding="utf-8")
    assert "mapping_ground_truth_fast import collect_mapping_from_canonical_gt" in cli


def test_fast_collector_materializes_only_relation_label_thumbnails() -> None:
    source = COLLECTOR.read_text(encoding="utf-8")
    assert "label_crop_ids" in source
    assert "block_crop_policy\": \"relation_labels_only" in source
    assert "materialized_label_crops" in source
    # The old path wrote every block image. The fast path chooses the small set
    # of label IDs first and writes only those thumbnails.
    assert "for block_id in sorted(label_crop_ids):" in source
    assert "payload[\"crop_path\"] = crop_paths.get(block.block_id, \"\")" in source
    assert "complete in %.2fs" in source
    assert "DB=%.2fs" in source
    assert "suggestions=%.2fs" in source


def test_fast_suggestions_cache_pipeline_a_geometry_per_source() -> None:
    source = SUGGESTIONS.read_text(encoding="utf-8")
    # These expensive reads must remain outside the field x relation scoring loop.
    assert source.count("database.list_detection_annotations(") == 1
    assert source.count("database.list_detection_candidates(") == 1
    assert source.count("database.list_detected_blocks(") == 1
    assert "geometry_by_value" in source
    assert "if value_block_id not in geometry_by_value:" in source
    assert "annotations=annotations" in source
    assert "candidates=candidates" in source
    assert "database.get_detected_block(" not in source


def test_fast_suggestions_store_results_in_one_transaction() -> None:
    source = SUGGESTIONS.read_text(encoding="utf-8")
    assert "with database.connect() as db:" in source
    assert "database._upsert_mapping_in_connection(" in source
    assert "database.upsert_mapping(" not in source
