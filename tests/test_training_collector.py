from pathlib import Path

import cv2
import numpy as np

from isala_ocr.config import AppConfig, FieldSpec, Profile
from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.base import OCREngine
from isala_ocr.training.collector import collect_samples
from isala_ocr.training.db import TrainingDatabase


class FakeRecognitionEngine(OCREngine):
    def recognize_many(self, images, whitelists=None):
        del whitelists
        return [[OCRToken(text=f" raw-{index} mI ", confidence=0.8)] for index, _ in enumerate(images)]

    def info(self):
        return {"provider": "fake"}


def test_collector_saves_roi_crops_and_raw_output_without_source_name(tmp_path: Path):
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    source = tmp_path / "patient-name-should-not-be-stored.png"
    assert cv2.imwrite(str(source), image)
    profile = Profile(
        name="test",
        description="",
        reference_width=200,
        reference_height=100,
        anchors=[],
        fields=[
            FieldSpec(
                key="value",
                label="Value",
                roi=Box(10, 20, 110, 60),
                unit=None,
                minimum=None,
                maximum=None,
                decimals=None,
                allow_missing=False,
                whitelist=None,
            )
        ],
        consistency_rules=[],
    )
    config = AppConfig(
        raw={"training": {"collection": {"padding_pixels": 0}}},
        path=tmp_path / "app.yaml",
        profile_path=tmp_path / "profile.yaml",
        profile=profile,
    )
    workspace = tmp_path / "training"
    result = collect_samples(source, workspace, config, FakeRecognitionEngine())
    assert result["added_samples"] == 1
    database = TrainingDatabase(workspace / "samples.sqlite3")
    rows = database.list_samples()
    assert len(rows) == 1
    row = rows[0]
    assert row["raw_ocr"] == " raw-0 mI "
    assert "patient-name" not in row["sample_id"]
    assert "patient-name" not in row["crop_path"]
    assert (workspace / row["crop_path"]).is_file()
