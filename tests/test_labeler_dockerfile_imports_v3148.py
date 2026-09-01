from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "infrastructure/docker/Dockerfile.labeler"
TRAINING_INIT = ROOT / "application/src/isala_ocr/training/__init__.py"


def test_labeler_image_copies_step7_evaluation_policy_module():
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    training_init = TRAINING_INIT.read_text(encoding="utf-8")

    assert "table_model_evaluation_policy" in training_init
    assert "COPY application/src/isala_ocr/training /app/src/isala_ocr/training" in dockerfile
