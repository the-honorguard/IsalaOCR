from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "application/src/isala_ocr/training/recognition_ground_truth.py"
GT_WEB = ROOT / "application/src/isala_ocr/training/recognition_ground_truth_web.py"
DATASET = ROOT / "application/src/isala_ocr/training/dataset.py"
METADATA = ROOT / "application/src/isala_ocr/training/recognition_model_factory.py"
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
MENU = ROOT / "automation/powershell/training-menu.ps1"
ARCH = ROOT / "docs/architecture/model-factory-and-application-processing.md"
VERSION = ROOT / "project/VERSION"


def test_recognition_gt_is_built_directly_from_canonical_geometry_without_mapping():
    text = GT.read_text(encoding="utf-8")

    assert 'EXTRACTION_METHOD = "canonical_gt_cell"' in text
    assert "list_ground_truth_cells" in text
    assert "list_ground_truth_sources" in text
    assert 'field_key": f"recognition.' in text
    assert 'review_roi(sample_id, "deferred"' in text
    assert "mapping.py" not in text
    assert "application_processing" not in text
    assert "field_definitions" not in text


def test_recognition_dataset_accepts_only_reviewed_neutral_gt_not_application_mapping():
    text = DATASET.read_text(encoding="utf-8")

    assert "RECOGNITION_GT_METHOD" in text
    assert "WHERE extraction_method=?" in text
    assert "AND status='accepted'" in text
    assert "AND exact_label IS NOT NULL" in text
    assert "canonical_table_cell_recognition_gt" in text
    assert "db.accepted()" not in text
    assert "mapped_generic" not in text


def test_literal_missing_markers_belong_to_recognition_gt_before_application_semantics():
    review = GT_WEB.read_text(encoding="utf-8")
    architecture = ARCH.read_text(encoding="utf-8")

    assert "A lone '-', '–' or '—'" in review
    assert "is NOT converted to null" in review
    assert 'action = "accepted" if exact != "" else "excluded"' in review
    assert "A lone `-`, `–` or `—` remains literal recognition Ground Truth" in architecture
    assert "missing/null" in architecture


def test_model_factory_order_places_recognition_before_application_processing():
    base = BASE.read_text(encoding="utf-8")
    metadata = METADATA.read_text(encoding="utf-8")
    menu = MENU.read_text(encoding="utf-8")

    assert '"recognition-gt"' in metadata
    assert '"recognition-review"' in metadata
    assert '"recognition-dataset": (9' in metadata
    assert '"recognition-train": (11' in metadata
    assert '"recognition-models": (13' in metadata

    recognition = base.index("MODEL FACTORY · RECOGNITION")
    bundle = base.index("EINDPRODUCT · MODEL BUNDLE")
    application = base.index("FASE 2 · APPLICATION PROCESSING · OPTIONEEL")
    assert recognition < bundle < application

    assert '"7"  = @{ Name = "Recognition-GT maken"' in menu
    assert '"13" = @{ Name = "Recognition-model activeren"' in menu
    assert '"A1" = @{ Name = "Application Mapping Studio"' in menu
    assert menu.index('"13" = @{ Name = "Recognition-model activeren"') < menu.index('"A1" = @{ Name = "Application Mapping Studio"')


def test_existing_application_mapping_is_preserved_as_optional_phase_two():
    base = BASE.read_text(encoding="utf-8")
    architecture = ARCH.read_text(encoding="utf-8")

    assert "Application Mapping Studio" in base
    assert "A{{ loop.index }}" in base
    assert "Existing Mapping Studio work is deliberately preserved" in architecture
    assert "Historical `mapped_generic` samples" in architecture


def test_recognition_model_factory_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.16.0"
