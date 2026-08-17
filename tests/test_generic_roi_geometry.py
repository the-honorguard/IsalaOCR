from __future__ import annotations

from pathlib import Path

from isala_ocr.models import Box, OCRToken
from isala_ocr.training.db import TrainingDatabase
from isala_ocr.training.generic_detection import detect_generic_structure
from isala_ocr.training.mapping import resolve_value_roi_box


def _store_detection(database: TrainingDatabase, source_id: str, shape, tokens):
    blocks, relations, _ = detect_generic_structure(source_id, shape, tokens)
    source_payload = {
        "source_id": source_id,
        "image_width": shape[1],
        "image_height": shape[0],
        "render_path": f"source_renders/{source_id}.png",
        "detector_version": "test",
        "token_count": len(tokens),
    }
    database.replace_generic_detection(
        source_payload,
        [{**block.as_dict(), "crop_path": ""} for block in blocks],
        [relation.as_dict() for relation in relations],
    )
    localization = []
    for index, token in enumerate(tokens):
        if token.box is None:
            continue
        localization.append({
            "candidate_id": f"loc-{index}", "source_id": source_id, "confidence": token.confidence,
            "source_kind": "text_geometry", "source_refs": [], "crop_path": "",
            "x1": token.box.x1, "y1": token.box.y1, "x2": token.box.x2, "y2": token.box.y2,
        })
    database.replace_localization_detection(source_payload, localization, [])
    return blocks, relations


def test_adjacent_table_rows_are_not_merged_into_one_semantic_label() -> None:
    tokens = [
        OCRToken("Stroke Volume", 0.99, Box(5, 100, 80, 114)),
        OCRToken("150.8 ml", 0.99, Box(125, 100, 175, 114)),
        OCRToken("Cardiac Output", 0.99, Box(5, 116, 90, 130)),
        OCRToken("9.0 L/min", 0.99, Box(125, 116, 180, 130)),
    ]
    blocks, relations, _ = detect_generic_structure("source", (300, 1024, 3), tokens)
    labels = [block.text for block in blocks if block.block_type == "semantic" and block.role == "label"]
    assert "Stroke Volume" in labels
    assert "Cardiac Output" in labels
    assert "Stroke Volume Cardiac Output" not in labels

    by_id = {block.block_id: block for block in blocks}
    pairs = {
        (by_id[rel.label_block_id].text if rel.label_block_id else "", by_id[rel.value_block_id].text)
        for rel in relations
    }
    assert ("Stroke Volume", "150.8 ml") in pairs
    assert ("Cardiac Output", "9.0 L/min") in pairs


def test_distant_same_height_labels_are_kept_as_separate_candidates() -> None:
    tokens = [
        OCRToken("Stroke Volume", 0.99, Box(5, 50, 80, 64)),
        OCRToken("Cardiac Output", 0.99, Box(180, 50, 270, 64)),
        OCRToken("9.0 L/min", 0.99, Box(300, 50, 360, 64)),
    ]
    blocks, relations, _ = detect_generic_structure("source", (150, 800, 3), tokens)
    labels = [block.text for block in blocks if block.block_type == "semantic" and block.role == "label"]
    assert "Stroke Volume" in labels
    assert "Cardiac Output" in labels
    assert all("Stroke Volume Cardiac Output" != text for text in labels)
    by_id = {block.block_id: block for block in blocks}
    matched = [
        (by_id[rel.label_block_id].text if rel.label_block_id else "", by_id[rel.value_block_id].text)
        for rel in relations
    ]
    assert ("Cardiac Output", "9.0 L/min") in matched
    assert ("Stroke Volume", "9.0 L/min") not in matched


def test_semantic_value_uses_pipeline_a_candidate_geometry(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    tokens = [
        OCRToken("ED Volume", 0.99, Box(10, 20, 90, 40)),
        OCRToken("135.0 ml", 0.99, Box(120, 20, 180, 40)),
    ]
    blocks, _ = _store_detection(database, "source", (100, 400, 3), tokens)
    value = next(block for block in blocks if block.block_type == "semantic" and block.role == "value")

    roi, diagnostics = resolve_value_roi_box(database, value.block_id, 400, 100)
    assert diagnostics["geometry_source"].startswith("pipeline_a_candidate")
    assert roi == Box(120, 20, 180, 40)

def test_reviewed_adjusted_pipeline_a_box_is_authoritative_for_mapping_roi(tmp_path: Path) -> None:
    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    tokens = [OCRToken("ED Volume: 135.0 ml", 0.99, Box(10, 20, 210, 42))]
    blocks, _ = _store_detection(database, "source", (100, 400, 3), tokens)
    value = next(block for block in blocks if block.block_type == "semantic" and block.role == "value")
    database.review_detection_candidate(
        source_id="source", candidate_id="loc-0", review_status="adjusted",
        corrected_box=(120, 20, 185, 42), reason_code="too_large",
    )
    roi, diagnostics = resolve_value_roi_box(database, value.block_id, 400, 100)
    assert diagnostics["geometry_source"] == "pipeline_a_reviewed_annotation"
    assert roi == Box(120, 20, 185, 42)

def test_automatic_mapping_ignores_reference_range_relations(tmp_path: Path) -> None:
    from isala_ocr.training.mapping import suggest_mappings

    database = TrainingDatabase(tmp_path / "samples.sqlite3")
    database.upsert_field_definition(
        "measurement.ed_volume", "ED Volume", aliases=["ED Volume"], data_type="decimal", preferred_unit="ml"
    )
    tokens = [
        OCRToken("ED Volume", 0.99, Box(10, 20, 90, 40)),
        OCRToken("135.0 ml", 0.99, Box(120, 20, 180, 40)),
        OCRToken("103.0 ... 192.0 ml", 0.99, Box(220, 20, 360, 40)),
    ]
    _store_detection(database, "source", (100, 400, 3), tokens)
    suggestions = suggest_mappings(database, "source", minimum_score=0.1)
    assert len(suggestions) == 1
    assert suggestions[0]["value_text"] == "135.0 ml"



def test_detection_view_defaults_to_mapping_candidates_and_uses_roi_preview() -> None:
    root = Path(__file__).resolve().parents[1]
    webui = (root / "application" / "src" / "isala_ocr" / "training" / "webui.py").read_text(encoding="utf-8")
    template = (root / "application" / "src" / "isala_ocr" / "training" / "templates" / "generic_detection.html").read_text(encoding="utf-8")
    mapping_template = (root / "application" / "src" / "isala_ocr" / "training" / "templates" / "mapping_studio.html").read_text(encoding="utf-8")
    assert 'request.args.get("role", "candidates")' in webui
    assert 'resolve_value_roi_box(' in webui
    assert '?mode=roi' in template
    assert 'Mappingkandidaten' in template
    assert 'finale cropgeometrie' in mapping_template
