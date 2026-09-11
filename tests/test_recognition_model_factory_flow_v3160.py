from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "application/src/isala_ocr/training/recognition_ground_truth.py"
GT_WEB = ROOT / "application/src/isala_ocr/training/recognition_ground_truth_web.py"
DATASET = ROOT / "application/src/isala_ocr/training/dataset.py"
METADATA = ROOT / "application/src/isala_ocr/training/recognition_model_factory.py"
BASE = ROOT / "application/src/isala_ocr/training/templates/base.html"
MENU = ROOT / "automation/powershell/training-menu.ps1"
ARCH = ROOT / "documentation/architecture/model-factory-and-application-processing.md"
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

    # "recognition-gt"/"recognition-review" were later merged: recognition_model_factory.py
    # now installs "recognition-scope" (index 8) and a combined "recognition-gt-studio"
    # (index 9, GT + review in one page). recognition-dataset moved to index 10, and
    # the legacy train/evaluate/models routes were folded into the combined
    # "Recognition Model Factory" page, so they carry index=None.
    assert '"recognition-scope"' in metadata
    assert '"recognition-gt-studio"' in metadata
    assert '"index": 8' in metadata
    assert '"index": 9' in metadata
    assert '"recognition-dataset": (10' in metadata
    assert '"recognition-train": (None' in metadata
    assert '"recognition-evaluate": (None' in metadata
    assert '"recognition-models": (None' in metadata

    recognition = base.index("MODEL FACTORY · RECOGNITION")
    bundle = base.index("EINDPRODUCT · MODEL BUNDLE")
    application = base.index("FASE 2 · APPLICATION PROCESSING · OPTIONEEL")
    assert recognition < bundle < application

    assert '"10" = @{ Name = "Recognition GT Studio"; Url = "http://127.0.0.1:8088/recognition-gt-review" }' in menu
    assert '"13" = @{ Name = "Application Mapping Studio"; ActionId = "20" }' in menu
    assert menu.index('"10" = @{ Name = "Recognition GT Studio"') < menu.index('"13" = @{ Name = "Application Mapping Studio"')


def test_existing_application_mapping_is_preserved_as_optional_phase_two():
    base = BASE.read_text(encoding="utf-8")
    architecture = ARCH.read_text(encoding="utf-8")

    # base.html's own Mapping Studio step now just carries "Mapping Studio"
    # (menu.ps1 still calls its Application-phase entry "Application Mapping
    # Studio"); the static "A{{ loop.index }}" badge was replaced by the
    # per-step "application_number" Jinja expression.
    assert "Mapping Studio" in base
    assert "{% set application_number = " in base
    assert "are retained. Existing mapping" in architecture
    assert "data is not migrated or deleted by the Model Factory split." in architecture
    assert "Historical Mapping jobs/routes remain available as optional" in architecture


def test_recognition_model_factory_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.16.0"
