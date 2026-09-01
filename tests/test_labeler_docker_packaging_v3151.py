from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "infrastructure/docker/Dockerfile.labeler"
VERSION = ROOT / "project/VERSION"


def test_labeler_copies_complete_training_and_application_processing_packages():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "COPY application/src/isala_ocr/application_processing /app/src/isala_ocr/application_processing" in text
    assert "COPY application/src/isala_ocr/training /app/src/isala_ocr/training" in text
    assert "COPY application/src/isala_ocr/training/mapping.py" not in text


def test_labeler_build_smoke_tests_webui_imports():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "import isala_ocr.application_processing" in text
    assert "from isala_ocr.training.webui import create_web_app" in text
    assert "assert callable(create_web_app)" in text


def test_labeler_packaging_fix_version():
    assert VERSION.read_text(encoding="utf-8").strip() == "3.16.0"
