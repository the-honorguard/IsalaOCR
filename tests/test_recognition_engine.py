from pathlib import Path

import numpy as np
import pytest

from isala_ocr.ocr.recognition import PaddleRecognitionEngine


def test_recognition_result_parser_keeps_text_verbatim():
    data = PaddleRecognitionEngine._result_data(
        {"res": {"rec_text": " 12O,7 mI ", "rec_score": 0.8}}
    )
    assert data["rec_text"] == " 12O,7 mI "


def test_recognition_input_is_converted_to_three_channel_uint8():
    gray = np.zeros((5, 6), dtype=np.float32)
    prepared = __import__("isala_ocr.ocr.paddle", fromlist=["PaddleEngine"]).PaddleEngine._prepare_image(gray)
    assert prepared.shape == (5, 6, 3)
    assert prepared.dtype == np.uint8


def _write_fake_inference_model(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "inference.json").write_text("{}", encoding="utf-8")
    (directory / "inference.pdiparams").write_bytes(b"weights")


def test_recognition_engine_selects_official_cached_model(tmp_path):
    expected = tmp_path / "official_models" / "PP-OCRv6_medium_rec"
    _write_fake_inference_model(expected)
    engine = PaddleRecognitionEngine(
        {
            "model_root": str(tmp_path),
            "recognition_model": "PP-OCRv6_medium_rec",
        }
    )
    assert engine._select_model_dir() == expected


def test_offline_recognition_fails_before_runtime_download(tmp_path):
    # Keep the cache non-empty so the failure specifically concerns the named
    # model rather than the general cache preflight.
    (tmp_path / "placeholder").write_text("prepared", encoding="utf-8")
    engine = PaddleRecognitionEngine(
        {
            "model_root": str(tmp_path),
            "recognition_model": "PP-OCRv6_medium_rec",
            "allow_downloads": False,
        }
    )
    with pytest.raises(RuntimeError, match="Offline recognition model is missing"):
        engine._load()
