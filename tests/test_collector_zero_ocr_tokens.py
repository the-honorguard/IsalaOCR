from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
import pytest
from isala_ocr.config import AppConfig, FieldSpec, Profile
from isala_ocr.models import Box
from isala_ocr.ocr.base import OCREngine
from isala_ocr.training import collector
from isala_ocr.training.collector import collect_mapping_detections
from isala_ocr.training.generic_detection import GenericBlock, GenericRelation


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


def test_zero_ocr_tokens_with_relations_from_other_geometry_are_not_flagged_as_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zero full-page-OCR-token source is not necessarily skipped by Mapping.

    Table structure (PP-Structure, or canonical GT in table_first mode) can
    recognize its own cell text independently of the generic full-page
    locator pass. Mapping only skips a source when it has no relations at
    all, so the per-source warning must not claim a skip when relations
    exist, and the zero-token tally must not count such a source.
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    assert cv2.imwrite(str(input_dir / "source.png"), image)

    def fake_detect_generic_structure(source_id, image_shape, tokens):
        del tokens
        block = GenericBlock(
            block_id="block-1",
            source_id=source_id,
            block_type="semantic",
            role="value",
            text="42",
            normalized_text="42",
            confidence=0.9,
            box=Box(10, 10, 30, 30),
            line_index=0,
            sequence_index=0,
        )
        relation = GenericRelation(
            relation_id="relation-1",
            source_id=source_id,
            label_block_id=None,
            value_block_id="block-1",
            unit_block_id=None,
            relation_type="table_cell",
            confidence=0.9,
            rank=1,
            context_text="",
        )
        diagnostics = {"ocr_token_count": 0}
        return [block], [relation], diagnostics

    monkeypatch.setattr(collector, "detect_generic_structure", fake_detect_generic_structure)

    config = _build_config(tmp_path)
    workspace = tmp_path / "training"
    engine = NoTextOCREngine()

    with caplog.at_level(logging.WARNING):
        manifest = collect_mapping_detections(input_dir, workspace, config, engine, engine)

    assert manifest["detected_sources"] == 1
    assert manifest["sources_without_ocr_tokens"] == 0

    warnings = "\n".join(record.getMessage() for record in caplog.records)
    assert "will process this source normally" in warnings
    assert "will skip this source" not in warnings
    assert "had zero OCR tokens" not in warnings
