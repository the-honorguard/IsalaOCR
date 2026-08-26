from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_table_first_detection_does_not_use_project_panel_profile_as_runtime_crop():
    collector = (ROOT / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    template = (ROOT / "application/src/isala_ocr/training/templates/process_step.html").read_text(encoding="utf-8")

    assert "table_preprocessing[\"panel_mode\"] = \"detected_full_image\"" in collector
    assert "detect_panels_with_benchmark" not in collector
    assert "full-image detectie" in template
    assert "panelprofiel ontbreekt" not in template


def test_table_cell_dataset_uses_reviewed_regions_then_detected_geometry():
    training = (ROOT / "application/src/isala_ocr/training/table_cell_training.py").read_text(encoding="utf-8")

    assert "def _training_panels(" in training
    assert "list_table_regions(root, source_id)" in training
    assert "db.list_detection_table_geometry(source_id)" in training
    assert "De regio’s worden full-image gedetecteerd" not in training
    assert "Stel eerst de table-panelen in" not in training
