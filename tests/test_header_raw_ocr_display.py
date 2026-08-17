from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_generic_detection_separates_observation_from_functional_mapping() -> None:
    detection = (
        ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "generic_detection.html"
    ).read_text(encoding="utf-8")
    mapping = (
        ROOT / "application" / "src" / "isala_ocr" / "training" / "templates" / "mapping_studio.html"
    ).read_text(encoding="utf-8")
    detector = (
        ROOT / "application" / "src" / "isala_ocr" / "training" / "generic_detection.py"
    ).read_text(encoding="utf-8")

    assert "wat is visueel gevonden, vóór functionele mapping" in detection
    assert "{{ block.text or 'Leeg blok' }}" in detection
    assert "Mogelijke label-waarderelaties" in detection
    assert "De betekenis wordt pas in de Mappingstudio bevestigd" in detection
    assert "Functioneel veld" in mapping
    assert "Gedetecteerde waarde" in mapping
    assert "field_key" not in detector.split("def detect_generic_structure", 1)[1].split("return blocks", 1)[0]
