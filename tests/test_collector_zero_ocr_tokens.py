from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from isala_ocr.config import AppConfig, FieldSpec, Profile
from isala_ocr.models import Box
from isala_ocr.ocr.base import OCREngine
from isala_ocr.training.collector import collect_mapping_detections


class NoTextOCREngine(OCREngine):
    """An OCR engine that behaves as if it found nothing on the page.

    This mirrors what a broken locator engine looks like from the caller's
    side: it returns successfully, just with an empty token list per image,
    instead of raising.
    """

    def recognize_many(self, images, whitelists=None):
        del whitelists
        return [[] for _ in images]

    def info(self):
        return {"provider": "fake-no-text"}


def _build_config(tmp_path: Path) -> AppConfig:
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
    return AppConfig(
        raw={
            "training": {
                "collection": {"table_structure": {"enabled": False}},
                "localization": {"strategy": "fusion"},
            }
        },
        path=tmp_path / "app.yaml",
        profile_path=tmp_path / "profile.yaml",
        profile=profile,
    )


def test_zero_ocr_tokens_are_flagged_at_detection_time(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(input_dir / "source.png"), image)

    config = _build_config(tmp_path)
    workspace = tmp_path / "training"
    engine = NoTextOCREngine()

    with caplog.at_level(logging.WARNING):
        manifest = collect_mapping_detections(input_dir, workspace, config, engine, engine)

    # An OCR engine that finds no text must not be reported as an ordinary
    # success: the source is still recorded (block/relation geometry can be
    # empty but valid), but the zero-token count is surfaced immediately
    # instead of only showing up two stages later during Mapping preparation.
    assert manifest["detected_sources"] == 1
    assert manifest["sources_without_ocr_tokens"] == 1

    warnings = "\n".join(record.getMessage() for record in caplog.records)
    assert "full-page OCR found no text token" in warnings
    assert "1/1 source(s) had zero OCR tokens" in warnings
