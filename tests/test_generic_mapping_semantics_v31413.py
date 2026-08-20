from isala_ocr.training.mapping import _context_score, _similarity, parse_mapped_value
from isala_ocr.training.mapping_semantics import is_missing_value_text, schema_candidate_score


def test_exact_alias_and_matching_unit_are_strong_without_field_specific_code():
    field = {
        "field_key": "custom.glucose",
        "display_name": "Glucose",
        "group_name": "Chemistry",
        "preferred_unit": "mmol/L",
        "aliases": ["GLU", "Glucose"],
    }
    relation = {
        "label_text": "GLU",
        "value_text": "5.4 mmol/L",
        "context_text": "Chemistry",
        "relation_type": "same_line_right",
        "confidence": 0.96,
    }

    score, evidence = schema_candidate_score(
        field,
        relation,
        similarity=_similarity,
        context_score=_context_score,
    )

    assert score >= 0.90
    assert evidence["exact_alias"] is True
    assert evidence["unit_match"] is True
    assert evidence["missing_value"] is False


def test_missing_marker_keeps_semantic_field_mapping_possible_without_a_unit():
    field = {
        "field_key": "custom.mass",
        "display_name": "Sample mass",
        "group_name": "Measurements",
        "data_type": "decimal",
        "preferred_unit": "g",
        "aliases": ["Mass"],
    }
    relation = {
        "label_text": "Mass",
        "value_text": "-",
        "context_text": "Measurements",
        "relation_type": "same_line_right",
        "confidence": 0.97,
    }

    score, evidence = schema_candidate_score(
        field,
        relation,
        similarity=_similarity,
        context_score=_context_score,
    )
    parsed = parse_mapped_value("-", field)

    assert is_missing_value_text("-")
    assert is_missing_value_text("–")
    assert is_missing_value_text("—")
    assert not is_missing_value_text("-5.2")
    assert not is_missing_value_text("-5.2 g")
    assert score >= 0.85
    assert evidence["exact_alias"] is True
    assert evidence["unit_match"] is False
    assert evidence["missing_value"] is True
    assert parsed["raw_text"] == "-"
    assert parsed["parsed_value"] is None
    assert parsed["parsed_unit"] == "g"
    assert parsed["parse_status"] == "missing"
    assert parsed["range_valid"] is None


def test_negative_numeric_value_is_still_parsed_as_a_number():
    field = {
        "field_key": "custom.delta",
        "display_name": "Delta",
        "data_type": "decimal",
        "preferred_unit": "g",
    }
    parsed = parse_mapped_value("-5.2 g", field)

    assert parsed["parsed_value"] == -5.2
    assert parsed["parsed_unit"] == "g"
    assert parsed["parse_status"] == "ok"


def test_unrelated_label_does_not_become_a_suggestion_just_from_unit_match():
    field = {
        "field_key": "custom.temperature",
        "display_name": "Temperature",
        "group_name": "Measurements",
        "preferred_unit": "kg",
        "aliases": ["Temp"],
    }
    relation = {
        "label_text": "Weight",
        "value_text": "82 kg",
        "context_text": "Measurements",
        "relation_type": "same_line_right",
        "confidence": 0.99,
    }

    score, evidence = schema_candidate_score(
        field,
        relation,
        similarity=_similarity,
        context_score=_context_score,
    )

    assert evidence["unit_match"] is True
    assert evidence["exact_alias"] is False
    assert score < 0.68
