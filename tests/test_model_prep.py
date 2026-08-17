from pathlib import Path

from isala_ocr.model_prep import download_models
from isala_ocr.models import OCRToken


def test_download_models_prepares_additional_official_recognition_model(monkeypatch, tmp_path):
    captured: list[dict[str, object]] = []
    pipeline_settings: list[dict[str, object]] = []

    class FakePipeline:
        def __init__(self, settings):
            pipeline_settings.append(dict(settings))
            self.settings = settings

        def recognize_many(self, images):
            return [[OCRToken(text="pipeline", confidence=1.0)]]

        def info(self):
            return {"kind": "pipeline"}

    class FakeRecognition:
        def __init__(self, settings):
            captured.append(dict(settings))
            self.settings = settings

        def recognize_many(self, images):
            return [[OCRToken(text="baseline", confidence=1.0)]]

        def info(self):
            return {"kind": "recognition", "model": self.settings["recognition_model"]}

    monkeypatch.setattr("isala_ocr.model_prep.PaddleEngine", FakePipeline)
    monkeypatch.setattr("isala_ocr.model_prep.PaddleRecognitionEngine", FakeRecognition)

    manifest = download_models(
        {
            "model_root": str(tmp_path),
            "recognition_model": "PP-OCRv6_small_rec",
            "active_recognition_model_dir": "/models/active-recognition",
            "recognition_model_dir": "/models/custom",
        },
        additional_recognition_models=["PP-OCRv6_medium_rec"],
    )

    assert pipeline_settings[0]["recognition_model"] == "PP-OCRv6_small_rec"
    assert "active_recognition_model_dir" not in pipeline_settings[0]
    assert "recognition_model_dir" not in pipeline_settings[0]
    assert captured[0]["recognition_model"] == "PP-OCRv6_medium_rec"
    assert "active_recognition_model_dir" not in captured[0]
    assert "recognition_model_dir" not in captured[0]
    assert manifest["additional_recognition_models"][0]["model"] == "PP-OCRv6_medium_rec"
    assert (Path(tmp_path) / "isala_ocr_model_manifest.json").is_file()
