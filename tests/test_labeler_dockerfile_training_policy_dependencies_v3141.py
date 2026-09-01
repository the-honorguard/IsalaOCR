from pathlib import Path


def test_labeler_image_includes_training_policy_modules_and_pillow() -> None:
    dockerfile = Path("infrastructure/docker/Dockerfile.labeler").read_text(encoding="utf-8")

    assert "COPY application/src/isala_ocr/training /app/src/isala_ocr/training" in dockerfile
    assert '"Pillow>=10,<13"' in dockerfile
