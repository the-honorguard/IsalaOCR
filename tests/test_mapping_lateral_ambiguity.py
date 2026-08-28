from pathlib import Path

from isala_ocr.training.mapping_lateral import (
    ambiguous_lateral_suffixes,
    lateral_candidate_allowed,
    relation_lateral_side,
)


ROOT = Path(__file__).resolve().parents[1]


def _field(key: str, group: str) -> dict[str, object]:
    return {"field_key": key, "group_name": group}


def test_generic_bilateral_measurement_is_not_auto_assigned_to_lv_or_rv() -> None:
    lv = _field("lv_ejection_fraction", "Left ventricle")
    rv = _field("rv_ejection_fraction", "Right ventricle")
    ambiguities = ambiguous_lateral_suffixes([lv, rv])
    relation = {
        "label_text": "Ejection Fraction",
        "context_text": "Ende Volume Normal Values Chuang",
    }

    assert ambiguities == {"ejection_fraction"}
    assert relation_lateral_side(relation) == ""
    assert lateral_candidate_allowed(lv, relation, ambiguities) is False
    assert lateral_candidate_allowed(rv, relation, ambiguities) is False


def test_explicit_lateral_context_allows_only_matching_ventricle() -> None:
    lv = _field("lv_stroke_volume", "Left ventricle")
    rv = _field("rv_stroke_volume", "Right ventricle")
    ambiguities = ambiguous_lateral_suffixes([lv, rv])

    left_relation = {
        "label_text": "Stroke Volume",
        "context_text": "Left ventricle results",
    }
    right_relation = {
        "label_text": "RV Stroke Volume",
        "context_text": "",
    }

    assert relation_lateral_side(left_relation) == "left"
    assert lateral_candidate_allowed(lv, left_relation, ambiguities) is True
    assert lateral_candidate_allowed(rv, left_relation, ambiguities) is False

    assert relation_lateral_side(right_relation) == "right"
    assert lateral_candidate_allowed(rv, right_relation, ambiguities) is True
    assert lateral_candidate_allowed(lv, right_relation, ambiguities) is False


def test_generic_alias_remains_valid_if_only_one_lateral_target_exists() -> None:
    lv = _field("lv_ejection_fraction", "Left ventricle")
    ambiguities = ambiguous_lateral_suffixes([lv])
    relation = {"label_text": "Ejection Fraction", "context_text": ""}

    assert ambiguities == set()
    assert lateral_candidate_allowed(lv, relation, ambiguities) is True


def test_custom_group_context_is_used_for_bilateral_prefixed_fields() -> None:
    aorta = _field("ao_flow", "Aortic measurements")
    pulmonary = _field("pa_flow", "Pulmonary measurements")
    ambiguities = ambiguous_lateral_suffixes([aorta, pulmonary])
    relation = {"label_text": "Flow", "context_text": "Aortic measurements"}

    assert ambiguities == {"flow"}
    assert lateral_candidate_allowed(aorta, relation, ambiguities) is True
    assert lateral_candidate_allowed(pulmonary, relation, ambiguities) is False


def test_fast_mapper_applies_lateral_guard_and_clears_old_suggestions() -> None:
    source = (ROOT / "application" / "src" / "isala_ocr" / "training" / "mapping_fast.py").read_text(encoding="utf-8")

    assert "ambiguous_lateral_suffixes(fields)" in source
    assert "lateral_candidate_allowed(field, relation, lateral_ambiguities)" in source
    assert "database.clear_suggested_mappings(source_id)" in source


def test_mapping_feedback_hidden_state_overrides_grid_display() -> None:
    css = (ROOT / "application" / "src" / "isala_ocr" / "training" / "static" / "step7-single-panel.css").read_text(encoding="utf-8")

    assert ".mapping-feedback-summary[hidden]" in css
    assert ".mapping-feedback-actions button[hidden]" in css
    assert "display: none !important;" in css
