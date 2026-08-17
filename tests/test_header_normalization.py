from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "src"))

from isala_ocr.config import FieldSpec, Profile
from isala_ocr.models import Box, OCRToken
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.dynamic_locator import locate_fields
from isala_ocr.training.header_normalization import (
    build_header_normalization_model,
    load_header_aliases,
)


def make_profile() -> Profile:
    fields = [
        FieldSpec(
            "lv_ed_volume", "Left ventricle ED Volume", Box(180, 80, 330, 104),
            "ml", None, None, 1, False, None, "lv", ("ED Volume",),
        ),
        FieldSpec(
            "lv_stroke_volume", "Left ventricle Stroke Volume", Box(180, 104, 330, 129),
            "ml", None, None, 1, False, None, "lv", ("Stroke Volume",),
        ),
        FieldSpec(
            "rv_ed_volume", "Right ventricle ED Volume", Box(180, 520, 330, 544),
            "ml", None, None, 1, False, None, "rv", ("ED Volume",),
        ),
    ]
    return Profile(
        name="header-profile",
        description="",
        reference_width=800,
        reference_height=800,
        anchors=[],
        fields=fields,
        consistency_rules=[],
        dynamic_extraction={
            "enabled": True,
            "panel_search_x2": 600,
            "fallback_label_column": [0, 170],
            "fallback_value_column": [180, 390],
            "header_search_x1": 130,
            "header_search_x2": 600,
            "right_panel_titles": ["Right ventricle Volume Result"],
            "value_headers": ["Endo Volume"],
            "normal_headers": ["Normal Values"],
            "label_match_threshold": 0.72,
            "row_half_height": 13,
        },
    )


def test_reviewed_row_headers_build_a_safe_alias_model(tmp_path: Path) -> None:
    profile = make_profile()
    rows = [
        {
            "sample_id": "a",
            "field_key": "lv_ed_volume",
            "locator_label_text": "ED VoIume",
            "header_review_status": "accepted",
            "header_target_field_key": "lv_ed_volume",
            "header_exact_label": "ED Volume",
        },
        {
            "sample_id": "b",
            "field_key": "rv_ed_volume",
            "locator_label_text": "ED VoIume",
            "header_review_status": "accepted",
            "header_target_field_key": "rv_ed_volume",
            "header_exact_label": "ED Volume",
        },
        {
            "sample_id": "c",
            "field_key": "lv_stroke_volume",
            "locator_label_text": "Stroxe Volurne",
            "header_review_status": "accepted",
            "header_target_field_key": "lv_stroke_volume",
            "header_exact_label": "Stroke Volume",
        },
    ]
    destination = tmp_path / "model.json"
    payload = build_header_normalization_model(rows, profile, destination)

    assert payload["included_example_count"] == 3
    assert payload["conflicts"] == []
    aliases = load_header_aliases(destination, profile)
    assert "ED VoIume" in aliases["lv_ed_volume"]
    assert "ED VoIume" in aliases["rv_ed_volume"]
    assert "Stroxe Volurne" in aliases["lv_stroke_volume"]


def test_conflicting_alias_inside_one_panel_is_not_activated(tmp_path: Path) -> None:
    profile = make_profile()
    rows = [
        {
            "sample_id": "a", "field_key": "lv_ed_volume",
            "locator_label_text": "Volurne", "header_review_status": "accepted",
            "header_target_field_key": "lv_ed_volume", "header_exact_label": "ED Volume",
        },
        {
            "sample_id": "b", "field_key": "lv_stroke_volume",
            "locator_label_text": "Volurne", "header_review_status": "accepted",
            "header_target_field_key": "lv_stroke_volume", "header_exact_label": "Stroke Volume",
        },
    ]
    destination = tmp_path / "model.json"
    payload = build_header_normalization_model(rows, profile, destination)
    aliases = load_header_aliases(destination, profile)

    assert len(payload["conflicts"]) == 1
    assert "Volurne" not in aliases.get("lv_ed_volume", ())
    assert "Volurne" not in aliases.get("lv_stroke_volume", ())


def test_dynamic_locator_uses_learned_header_alias() -> None:
    profile = make_profile()
    tokens = [
        OCRToken("Endo Volume", 0.95, Box(210, 55, 310, 68)),
        OCRToken("Normal Values", 0.95, Box(450, 55, 555, 68)),
        OCRToken("XYZ", 0.95, Box(10, 90, 80, 103)),
        OCRToken("123 ml", 0.95, Box(220, 90, 285, 103)),
    ]
    without, _ = locate_fields((800, 800), tokens, profile, padding_pixels=0)
    with_alias, diagnostics = locate_fields(
        (800, 800), tokens, profile, padding_pixels=0,
        learned_aliases={"lv_ed_volume": ("XYZ",)},
    )
    without_by_key = {item.field.key: item for item in without}
    with_by_key = {item.field.key: item for item in with_alias}

    assert without_by_key["lv_ed_volume"].method == "fixed_fallback"
    assert with_by_key["lv_ed_volume"].method == "dynamic_token_box"
    assert with_by_key["lv_ed_volume"].matched_label == "XYZ"
    assert diagnostics["learned_alias_count"] == 1


def sample_payload(label: str = "ED VoIume") -> dict:
    return {
        "sample_id": "source_lv_ed_volume",
        "source_id": "source",
        "profile": "header-profile",
        "field_key": "lv_ed_volume",
        "field_label": "Left ventricle ED Volume",
        "crop_path": "crops/value.png",
        "raw_ocr": "123 ml",
        "raw_confidence": 0.9,
        "raw_variant": "test",
        "image_width": 800,
        "image_height": 800,
        "roi_x1": 180,
        "roi_y1": 80,
        "roi_x2": 330,
        "roi_y2": 104,
        "extraction_method": "dynamic_token_box",
        "locator_confidence": 0.7,
        "locator_label_text": label,
        "locator_version": "test",
        "header_crop_path": "header_crops/source/lv_ed_volume.png",
        "header_crop_sha256": "headerhash",
        "crop_sha256": "valuehash",
    }


def test_header_review_is_reset_when_locator_text_changes(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_sample(sample_payload())
    database.review_header(
        "source_lv_ed_volume", "accepted", "lv_ed_volume", "ED Volume", "checked"
    )
    changed = sample_payload("ED V0lume")
    database.upsert_sample(changed)
    stored = database.get("source_lv_ed_volume")

    assert stored is not None
    assert stored["header_review_status"] == "pending"
    assert stored["header_target_field_key"] == "lv_ed_volume"
    assert stored["header_exact_label"] == ""
