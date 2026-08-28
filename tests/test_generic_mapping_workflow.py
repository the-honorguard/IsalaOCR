from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from isala_ocr.config import load_config
from isala_ocr.models import Box, OCRToken
from isala_ocr.training.db import SCHEMA_VERSION, TrainingDatabase
from isala_ocr.training.generic_detection import detect_generic_structure
from isala_ocr.training.mapping import (
    materialize_confirmed_mappings,
    parse_mapped_value,
    recognize_approved_mapped_samples,
)

ROOT = Path(__file__).resolve().parents[1]


def test_generic_detector_splits_multiple_key_value_pairs_without_field_keys() -> None:
    tokens = [
        OCRToken("Study info: HR:", 0.96, Box(10, 10, 110, 28)),
        OCRToken("92 bpm", 0.98, Box(120, 10, 180, 28)),
        OCRToken("BSA:", 0.97, Box(200, 10, 240, 28)),
        OCRToken("2.13 m²", 0.98, Box(250, 10, 320, 28)),
        OCRToken("ED Volume", 0.99, Box(10, 50, 100, 68)),
        OCRToken("106.8 ml", 0.99, Box(120, 50, 190, 68)),
        OCRToken("88.0 ... 227.0 ml", 0.94, Box(220, 50, 360, 68)),
    ]

    blocks, relations, diagnostics = detect_generic_structure(
        "source", (100, 400, 3), tokens
    )
    by_id = {block.block_id: block for block in blocks}
    pairs = [
        (
            by_id[relation.label_block_id].text if relation.label_block_id else "",
            by_id[relation.value_block_id].text,
        )
        for relation in relations
    ]

    assert ("HR", "92 bpm") in pairs
    assert ("BSA", "2.13 m²") in pairs
    assert ("ED Volume", "106.8 ml") in pairs
    assert diagnostics["relation_count"] >= 5
    assert all("field_key" not in block.as_dict() for block in blocks)
    assert all("field_key" not in relation.as_dict() for relation in relations)


def test_confirmed_mapping_becomes_roi_then_value_output(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    database = TrainingDatabase(workspace / "samples.sqlite3")
    assert SCHEMA_VERSION >= 8

    image = np.full((100, 300, 3), 255, dtype=np.uint8)
    cv2.putText(image, "HR: 92 bpm", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    render = workspace / "source_renders" / "source.png"
    render.parent.mkdir(parents=True)
    assert cv2.imwrite(str(render), image)

    tokens = [
        OCRToken("HR:", 0.98, Box(10, 30, 65, 62)),
        OCRToken("92 bpm", 0.99, Box(75, 30, 165, 62)),
    ]
    blocks, relations, _ = detect_generic_structure("source", image.shape, tokens)
    block_payloads = []
    for block in blocks:
        payload = block.as_dict()
        crop = image[block.box.y1:block.box.y2, block.box.x1:block.box.x2]
        crop_path = workspace / "detected_blocks" / "source" / f"{block.block_id}.png"
        crop_path.parent.mkdir(parents=True, exist_ok=True)
        assert cv2.imwrite(str(crop_path), crop)
        payload["crop_path"] = crop_path.relative_to(workspace).as_posix()
        block_payloads.append(payload)
    database.replace_generic_detection(
        {
            "source_id": "source",
            "image_width": image.shape[1],
            "image_height": image.shape[0],
            "render_path": "source_renders/source.png",
            "detector_version": "test",
            "token_count": len(tokens),
        },
        block_payloads,
        [relation.as_dict() for relation in relations],
    )
    database.replace_localization_detection(
        {
            "source_id": "source", "image_width": image.shape[1], "image_height": image.shape[0],
            "render_path": "source_renders/source.png", "detector_version": "test-localization", "token_count": len(tokens),
        },
        [{"candidate_id": "hr-value-roi", "source_id": "source", "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 73, "y1": 28, "x2": 167, "y2": 64}],
        [],
    )
    database.upsert_field_definition(
        "study.heart_rate_bpm",
        "Heart rate",
        group_name="Study information",
        data_type="integer",
        preferred_unit="bpm",
        aliases=["HR", "Heart rate"],
        minimum_value=20,
        maximum_value=250,
    )
    relation = next(
        item for item in database.list_detected_relations("source")
        if item["label_text"] == "HR"
    )
    mapping = database.upsert_mapping(
        source_id="source",
        field_key="study.heart_rate_bpm",
        relation_id=relation["relation_id"],
        label_block_id=relation["label_block_id"],
        value_block_id=relation["value_block_id"],
        status="confirmed",
        mapping_confidence=0.99,
    )
    assert mapping["value_text"] == "92 bpm"

    config = load_config(ROOT / "application" / "config" / "app.yaml")
    manifest = materialize_confirmed_mappings(
        workspace, config, source_id="source", recognize=False
    )
    assert manifest["confirmed_mapping_count"] == 1
    sample_id = "source_study.heart_rate_bpm"
    sample = database.get(sample_id)
    assert sample is not None
    assert sample["extraction_method"] == "mapped_generic"
    assert sample["raw_variant"] == "awaiting_value_recognition"
    assert sample["roi_review_status"] == "correct"

    class FakeEngine:
        def warmup(self) -> None:
            return None

        def recognize_many(self, images):
            return [[OCRToken("92 bpm", 0.995)] for _ in images]

        def info(self):
            return {"provider": "fake", "recognition_model": "test"}

    recognized = recognize_approved_mapped_samples(
        workspace, FakeEngine(), source_id="source"
    )
    assert recognized["recognized_samples"] == 1
    output = json.loads(
        (workspace / "extracted_output" / "source.json").read_text(encoding="utf-8")
    )
    value = output["measurements"]["study.heart_rate_bpm"]
    assert value["raw_text"] == "92 bpm"
    assert value["parsed_value"] == 92
    assert value["parsed_unit"] == "bpm"
    assert value["range_valid"] is True


def test_value_parser_preserves_raw_text_and_reports_range() -> None:
    parsed = parse_mapped_value(
        " 501,2 kg ",
        {
            "data_type": "decimal",
            "preferred_unit": "kg",
            "minimum_value": 1,
            "maximum_value": 500,
        },
    )
    assert parsed["raw_text"] == " 501,2 kg "
    assert parsed["parsed_value"] == 501.2
    assert parsed["parsed_unit"] == "kg"
    assert parsed["range_valid"] is False


def test_generic_detector_recognizes_common_cmr_units_without_field_configuration() -> None:
    from isala_ocr.training.generic_detection import looks_like_unit, looks_like_value

    for unit in ("ml", "ml/m²", "L/min", "L/(min*m²)", "l/(min·m²)", "g", "gr", "gr/m²", "%"):
        assert looks_like_unit(unit), unit
        assert looks_like_value(f"12.3 {unit}"), unit


def test_default_schema_contains_dutch_aliases_but_detector_remains_neutral() -> None:
    from isala_ocr.training.mapping import default_field_definitions

    config = load_config(ROOT / "application" / "config" / "app.yaml")
    definitions = {item["field_key"]: item for item in default_field_definitions(config.profile)}
    assert "Ejectiefractie" in definitions["lv_ejection_fraction"]["aliases"]
    assert "Slagvolume" in definitions["rv_stroke_volume"]["aliases"]
    assert "Hartminuutvolume" in definitions["lv_cardiac_output"]["aliases"]


def test_dutch_alias_and_panel_context_create_reviewable_mapping_suggestion(tmp_path: Path) -> None:
    from isala_ocr.training.mapping import ensure_default_field_definitions, suggest_mappings

    workspace = tmp_path / "workspace"
    database = TrainingDatabase(workspace / "samples.sqlite3")
    config = load_config(ROOT / "application" / "config" / "app.yaml")
    ensure_default_field_definitions(database, config.profile)

    label = {
        "block_id": "label", "source_id": "source", "block_type": "semantic",
        "role": "label", "text": "Ejectiefractie", "normalized_text": "ejectiefractie",
        "confidence": 0.99, "x1": 10, "y1": 10, "x2": 110, "y2": 30,
        "line_index": 0, "sequence_index": 0, "parent_block_id": "",
        "context_text": "Volumeresultaat linkerventrikel", "crop_path": "",
    }
    value = {
        "block_id": "value", "source_id": "source", "block_type": "semantic",
        "role": "value", "text": "56 %", "normalized_text": "56 %",
        "confidence": 0.99, "x1": 130, "y1": 10, "x2": 180, "y2": 30,
        "line_index": 0, "sequence_index": 1, "parent_block_id": "",
        "context_text": "Volumeresultaat linkerventrikel", "crop_path": "",
    }
    relation = {
        "relation_id": "relation", "source_id": "source", "label_block_id": "label",
        "value_block_id": "value", "unit_block_id": "",
        "relation_type": "same_line_right", "confidence": 0.99, "rank": 1,
        "context_text": "Volumeresultaat linkerventrikel",
    }
    database.replace_generic_detection(
        {
            "source_id": "source", "image_width": 300, "image_height": 100,
            "render_path": "source_renders/source.png", "detector_version": "test",
            "token_count": 2,
        },
        [label, value],
        [relation],
    )
    database.replace_localization_detection(
        {
            "source_id": "source", "image_width": 300, "image_height": 100,
            "render_path": "source_renders/source.png", "detector_version": "test-localization", "token_count": 2,
        },
        [{"candidate_id": "ef-value-roi", "source_id": "source", "confidence": 0.99, "source_kind": "text_geometry", "source_refs": [], "crop_path": "", "x1": 128, "y1": 8, "x2": 182, "y2": 32}],
        [],
    )

    suggestions = suggest_mappings(database, "source")
    assert any(
        item["field_key"] == "lv_ejection_fraction" and item["status"] == "suggested"
        for item in suggestions
    )
    assert not any(item["status"] == "confirmed" for item in suggestions)


def test_mapping_actions_have_stage_specific_preflight_without_requiring_input_files() -> None:
    preflight = (ROOT / "automation" / "powershell" / "preflight.ps1").read_text(encoding="utf-8")
    assert '"20" = @{ Name = "Prepare Mapping Studio data after geometry gate"; Script = "prepare-mapping-data.ps1"; Profile = "mapping-prepare" }' in preflight
    assert '"21" = @{ Name = "Apply current raster/cell mappings"; Script = "apply-mappings.ps1"; Profile = "mapping-apply" }' in preflight
    assert '"22" = @{ Name = "Read values from current raster/cells"; Script = "read-mapped-values.ps1"; Profile = "value-read" }' in preflight
    mapping_block = preflight.split('"mapping-apply" {', 1)[1].split('"value-read" {', 1)[0]
    value_block = preflight.split('"value-read" {', 1)[1].split('"label" {', 1)[0]
    assert "Get-IsalaInputFileCount" not in mapping_block
    assert "Get-IsalaInputFileCount" not in value_block
    assert "source_renders" in mapping_block
    assert "isala_ocr_model_manifest.json" in value_block
