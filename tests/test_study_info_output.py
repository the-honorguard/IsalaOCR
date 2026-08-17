from __future__ import annotations

import json
from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.study_info import extract_study_info


def token(text: str, x1: int, y1: int, x2: int, y2: int, confidence: float = 0.97) -> OCRToken:
    return OCRToken(text=text, confidence=confidence, box=Box(x1, y1, x2, y2))


def test_parses_study_info_as_separate_output_fields() -> None:
    result = extract_study_info([
        token(
            "Study info : HR: 79 bpm BSA: 2.35 m² (Mosteller) Height: 1.83 m Weight: 109.0 kg Gender: M",
            10, 100, 620, 118,
        )
    ])

    assert result.detected is True
    assert result.heart_rate_bpm == 79
    assert result.bsa_m2 == 2.35
    assert result.bsa_method == "Mosteller"
    assert result.height_m == 1.83
    assert result.weight_kg == 109.0
    assert result.gender == "M"
    assert result.raw_values["heart_rate_bpm"] == "79 bpm"
    assert result.raw_values["bsa_m2"] == "2.35 m² (Mosteller)"
    assert result.valid["height_m"] is True


def test_parses_fragmented_detector_tokens_and_converts_centimetres() -> None:
    tokens = [
        token("Study info", 10, 200, 80, 218),
        token("HR: 62 bpm", 90, 200, 165, 218),
        token("BSA: 1,87 m2 (Mosteller)", 175, 200, 335, 218),
        token("Height: 176 cm", 345, 200, 445, 218),
        token("Weight: 78,5 kg", 455, 200, 555, 218),
        token("Gender: F", 565, 200, 630, 218),
    ]
    result = extract_study_info(tokens)

    assert result.heart_rate_bpm == 62
    assert result.bsa_m2 == 1.87
    assert result.height_m == 1.76
    assert result.weight_kg == 78.5
    assert result.gender == "F"


def test_best_complete_duplicate_study_line_wins() -> None:
    tokens = [
        token("Study info HR: 80 bpm BSA: 2.0 m2", 10, 100, 300, 118, 0.99),
        token(
            "Study info HR: 79 bpm BSA: 2.35 m2 (Mosteller) Height: 1.83 m Weight: 109.0 kg Gender: M",
            10, 400, 620, 418, 0.95,
        ),
    ]
    result = extract_study_info(tokens)
    assert result.heart_rate_bpm == 79
    assert result.roi == Box(10, 400, 620, 418)


def test_collector_and_result_schema_expose_named_study_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    collector = (root / "application/src/isala_ocr/training/collector.py").read_text(encoding="utf-8")
    template = (root / "application/src/isala_ocr/training/templates/document.html").read_text(encoding="utf-8")
    webui = (root / "application/src/isala_ocr/training/webui.py").read_text(encoding="utf-8")
    schema = json.loads((root / "application/schemas/result.schema.json").read_text(encoding="utf-8"))

    assert '"extracted_output"' in collector
    assert '"study_info": study_info.as_dict()' in collector
    for key in ("heart_rate_bpm", "bsa_m2", "bsa_method", "height_m", "weight_kg", "gender"):
        assert key in schema["properties"]["study_info"]["properties"]
        assert key in webui
    assert "Output-JSON openen" in template
    assert "Volledige ruwe OCR-regel" in template
