from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from isala_ocr.config import AppConfig, FieldSpec, Profile
from isala_ocr.models import Box
from isala_ocr.ocr.base import OCREngine
from isala_ocr.training.collector import collect_mapping_detections


class NoTextOCREngine(OCREngine):
    """Behaves like a locator engine that finds nothing -- see
    test_collector_zero_ocr_tokens.py for why this is enough to exercise
    collect_mapping_detections() without a real OCR/table model.
    """

    def recognize_many(self, images, whitelists=None):
        del whitelists
        return [[] for _ in images]

    def info(self):
        return {"provider": "fake-no-text"}

    def warmup(self):
        pass


def _build_config(tmp_path: Path) -> AppConfig:
    profile = Profile(
        name="test", description="", reference_width=200, reference_height=100,
        anchors=[],
        fields=[
            FieldSpec(
                key="value", label="Value", roi=Box(10, 20, 110, 60), unit=None,
                minimum=None, maximum=None, decimals=None, allow_missing=False, whitelist=None,
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


def test_a_single_targeted_file_does_not_wipe_other_sources_generic_detections(tmp_path: Path) -> None:
    """Regression test: a proefpagina retest (job 61) passes its own single
    DICOM/image file as ``input_path`` instead of the whole input directory
    (see selected_input_files()'s docstring). Processing that one file must
    never delete every other source's already-recorded generic_detections/
    detected_blocks -- previously _collect_mapping_detections() wiped both
    directories wholesale on every call, so a single proefpagina rerun
    silently destroyed every other source's Identificatie data project-wide,
    with only the most-recently-run source's file surviving. Only a
    whole-project rebuild (Action 20, which passes the input *directory*) may
    wipe and regenerate everything.
    """
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    # Distinct pixel content: decoded.source_id is a hash of the file's own
    # bytes, so two byte-identical images would collapse onto the same id.
    source_a = input_dir / "source_a.png"
    source_b = input_dir / "source_b.png"
    assert cv2.imwrite(str(source_a), np.full((100, 200, 3), 255, dtype=np.uint8))
    assert cv2.imwrite(str(source_b), np.full((100, 200, 3), 128, dtype=np.uint8))

    config = _build_config(tmp_path)
    workspace = tmp_path / "training"
    engine = NoTextOCREngine()

    # A full-project pass (directory input, like Action 20) records both sources.
    collect_mapping_detections(input_dir, workspace, config, engine, engine)
    diagnostics_root = workspace / "generic_detections"
    before = sorted(diagnostics_root.glob("*.json"))
    assert len(before) == 2

    # A targeted single-file rerun of just one of them (like a proefpagina
    # retest) must not remove the other source's file.
    collect_mapping_detections(source_a, workspace, config, engine, engine)
    after = sorted(diagnostics_root.glob("*.json"))
    assert len(after) == 2
    assert {path.name for path in before} == {path.name for path in after}
