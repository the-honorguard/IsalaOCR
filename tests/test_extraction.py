import numpy as np

from isala_ocr.config import FieldSpec, Profile
from isala_ocr.extraction import ExtractionSettings, extract
from isala_ocr.models import Box, OCRToken
from isala_ocr.ocr.base import OCREngine


class FakeEngine(OCREngine):
    def recognize_many(self, images, whitelists=None):
        assert len(images) == 2
        return [
            [OCRToken("128.7 ml", 0.95)],
            [OCRToken("61.6 ml", 0.94)],
        ]

    def info(self):
        return {"provider": "fake"}


def test_extracts_configured_fields():
    profile = Profile(
        name="test",
        description="",
        reference_width=100,
        reference_height=100,
        anchors=[],
        fields=[
            FieldSpec("ed", "ED", Box(0, 0, 50, 20), "ml", 0, 500, 1, False, None),
            FieldSpec("es", "ES", Box(0, 20, 50, 40), "ml", 0, 500, 1, False, None),
        ],
        consistency_rules=[],
    )
    _, fields = extract(
        np.zeros((100, 100, 3), dtype=np.uint8),
        profile,
        FakeEngine(),
        ExtractionSettings(
            variants=("grayscale_upscale",),
            upscale_factor=2.0,
            padding_pixels=0,
            minimum_confidence=0.5,
            verify_anchors=False,
        ),
    )
    assert [item.value for item in fields] == [128.7, 61.6]
    assert all(item.valid for item in fields)
