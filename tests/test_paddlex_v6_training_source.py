from __future__ import annotations

from pathlib import Path


def test_training_image_overlays_pinned_paddlex_v6_source():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "infrastructure" / "docker" / "Dockerfile.training").read_text(encoding="utf-8")
    assert "PADDLEX_SOURCE_VERSION=3.7.2" in dockerfile
    assert "6a60b4595e2d51460f7f51326672adca86b89ff9ecfd02ac348fb69739e0093c" in dockerfile
    assert "PP-OCRv6_medium_rec.yaml" in dockerfile
    assert "/opt/paddlex-source[ocr]" in dockerfile
    assert "PADDLE_PACKAGE=paddlepaddle==3.2.2" in dockerfile
    assert 'python3 -m pip install --upgrade "${PADDLE_PACKAGE}"' in dockerfile
    assert "PADDLEOCR_SOURCE_COMMIT=2661c7c0ef5c613e8f93c6e93b2e052399f0f854" in dockerfile
    assert "PADDLEOCR_DICT_GIT_BLOB_SHA1=270082aa29aec1ff3ac74d0d575c90399216f74d" in dockerfile
    assert "ISALA_PPOCRV6_DICTIONARY=/opt/isala-training-resources/ppocrv6_dict.txt" in dockerfile
    assert 'git_blob = b"blob "' in dockerfile
    assert "PADDLE_PDX_LOCAL_FONT_FILE_PATH=/opt/isala-training-resources/DejaVuSans.ttf" in dockerfile
    assert 'Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"' in dockerfile
    assert 'ImageFont.truetype(str(destination), 24, encoding="utf-8")' in dockerfile
    assert 'for text in ("0123456789", ".,/%", "ml/m²")' in dockerfile
    assert "--deps_to_replace PaddleDetection.sklearn=None" in dockerfile


def test_prepare_verifies_training_config_before_success():
    root = Path(__file__).resolve().parents[1]
    runner = (root / "automation" / "training_runtime" / "paddlex_runner.py").read_text(encoding="utf-8")
    prepare_start = runner.index("def prepare(")
    prepare_end = runner.index("\ndef check(", prepare_start)
    prepare_body = runner[prepare_start:prepare_end]
    assert "main, config = _discover(args.model)" in prepare_body
    assert '"paddlex_config": str(config)' in prepare_body


def test_compose_passes_pinned_source_and_paddle_runtime_to_training_builds():
    root = Path(__file__).resolve().parents[1]
    compose = (root / "infrastructure" / "docker" / "compose.yaml").read_text(encoding="utf-8")
    assert compose.count("PADDLEX_SOURCE_VERSION:") >= 2
    assert compose.count("PADDLEX_SOURCE_SHA256:") >= 2
    assert compose.count("PADDLE_PACKAGE:") >= 2
    assert compose.count("PADDLE_INDEX_URL:") >= 2
    assert compose.count("APP_UID:") >= 2
    assert compose.count("APP_GID:") >= 2
    assert "training-image-cpu" in compose
    assert "training-image-gpu" in compose
    assert "paddlepaddle==3.2.2" in compose
    assert "paddlepaddle-gpu==3.2.2" in compose
