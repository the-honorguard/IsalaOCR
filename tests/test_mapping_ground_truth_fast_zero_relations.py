from __future__ import annotations

import logging
from pathlib import Path

import pytest

from isala_ocr.config import load_config
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.mapping_ground_truth_fast import collect_mapping_from_canonical_gt

ROOT = Path(__file__).resolve().parents[1]


def _seed_detection_source(
    database: TrainingDatabase, source_id: str, *, token_count: int
) -> None:
    database.replace_generic_detection(
        {
            "source_id": source_id,
            "image_width": 200,
            "image_height": 100,
            "render_path": f"source_renders/{source_id}.png",
            "detector_version": "test",
            "token_count": token_count,
        },
        [],
        [],
    )


def test_zero_relations_error_distinguishes_missing_ocr_from_unformed_relations(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    # One source where Detection/Recognition-OCR never found any text, and one
    # where OCR text existed but no label/value pair could be formed. Both must
    # be individually distinguishable in the failure output, otherwise an
    # operator cannot tell whether to re-run OCR or fix the canonical GT.
    _seed_detection_source(database, "source-no-ocr", token_count=0)
    _seed_detection_source(database, "source-with-ocr", token_count=5)

    config = load_config(ROOT / "application" / "config" / "app.yaml")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError) as excinfo:
            collect_mapping_from_canonical_gt(tmp_path, tmp_path, config, None)

    message = str(excinfo.value)
    assert "1 bron(nen) hadden 0 OCR-tokens" in message
    assert "1 bron(nen) hadden wel OCR-tekst maar geen label/waarde-relatie" in message

    warnings = "\n".join(record.getMessage() for record in caplog.records)
    assert "source-no-ocr" in warnings and "token_count=0" in warnings
    assert "opnieuw uit" in warnings
    assert "source-with-ocr" in warnings and "token_count=5" in warnings
    assert "canonical GT-celdekking" in warnings
