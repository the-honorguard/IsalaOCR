"""``_recognition_readout_stage_data`` (routes_documents.py) must show this
run's actual field-by-field Recognition read-out, not Recognition GT Studio's
own per-cell training crops.

A source that has also been used to build Recognition GT training data
(``recognition_ground_truth.py``) carries extra ``canonical_gt_cell``
samples under the same source_id, each defaulting its ``field_label`` to the
generic "Tabelcel" (see ``_build_recognition_ground_truth``'s docstring).
Before this fix, the proefpagina compare screen's STAP 6 mixed those in with
the real, meaningfully-labelled fields, so a training-pipeline origin with
GT-authoring history dumped dozens of unlabelled "Tabelcel" rows into the
comparison -- drowning out the real one -- while the freshly-rerun
proefpagina side (which never has such GT samples) stayed clean, making the
two sides look wildly different for no real reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("flask")

from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.recognition_ground_truth import EXTRACTION_METHOD as CANONICAL_GT_CELL_EXTRACTION_METHOD
from isala_ocr.training.routes_documents import _recognition_readout_stage_data

SOURCE_ID = "source-a"


def _sample(sample_id: str, *, field_key: str, field_label: str, raw_ocr: str, extraction_method: str) -> dict:
    return {
        "sample_id": sample_id, "source_id": SOURCE_ID, "profile": "cmr",
        "field_key": field_key, "field_label": field_label, "crop_path": "crops/x.png",
        "image_width": 8, "image_height": 8, "roi_x1": 0, "roi_y1": 0, "roi_x2": 4, "roi_y2": 4,
        "raw_ocr": raw_ocr, "raw_confidence": 0.9, "raw_variant": "original",
        "extraction_method": extraction_method, "status": "pending",
    }


def test_canonical_gt_cell_samples_are_excluded_from_the_readout(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample(_sample(
        "sample-real", field_key="lv_cardiac_output", field_label="Left ventricle Cardiac Output",
        raw_ocr="9.6 L/min", extraction_method="mapped_generic",
    ))
    for index in range(3):
        database.upsert_sample(_sample(
            f"recgt-{index}", field_key=f"recognition.cell-{index}", field_label="Tabelcel",
            raw_ocr="178.7 ml", extraction_method=CANONICAL_GT_CELL_EXTRACTION_METHOD,
        ))

    data = _recognition_readout_stage_data(SOURCE_ID, database=database)

    assert data is not None
    assert [row["field_label"] for row in data["samples"]] == ["Left ventricle Cardiac Output"]


def test_returns_none_when_only_canonical_gt_cell_samples_exist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    database.upsert_sample(_sample(
        "recgt-0", field_key="recognition.cell-0", field_label="Tabelcel",
        raw_ocr="178.7 ml", extraction_method=CANONICAL_GT_CELL_EXTRACTION_METHOD,
    ))

    assert _recognition_readout_stage_data(SOURCE_ID, database=database) is None
