from pathlib import Path


def test_training_image_fetches_pinned_paddleocr_source():
    text = Path("infrastructure/docker/Dockerfile.training").read_text(encoding="utf-8")
    assert "ARG PADDLEOCR_SOURCE_COMMIT=b03f46425e8ff4442b268ce449e3eef758146cd4" in text
    assert "isalaocr-paddleocr-source-cache" in text
    assert "PaddleOCR/archive/{commit}.tar.gz" in text
    assert "tools/train.py" in text
    assert "ISALA_PADDLEOCR_ROOT=/opt/isala-paddleocr" in text
    assert "vendor base image does not contain a complete PaddleOCR" in text
