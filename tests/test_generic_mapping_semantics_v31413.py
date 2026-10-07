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


def test_plain_unit_does_not_falsely_match_a_compound_unit_value():
    """A field whose unit is "ml" must not treat a "ml/m2" value as a match --
    ``normalize_text`` turns "/" into whitespace, so a naive containment check
    ("ml" in "93.1 ml m2") used to pass. This caused two real fields (ES
    Volume, unit "ml", and ED Volume/BSA, unit "ml/m2") to score identically
    high on each other's values, tipping an "exact_alias" tie the wrong way
    and swapping their readouts between two otherwise-identical pipeline runs.
    """
    field = {
        "field_key": "lv_es_volume",
        "display_name": "Left ventricle ES Volume",
        "group_name": "Left ventricle",
        "preferred_unit": "ml",
        "aliases": ["ES Volume"],
    }
    relation = {
        "label_text": "ES Volume",
        "value_text": "93.1 ml/m²",
        "context_text": "Links",
        "relation_type": "table_cell",
        "confidence": 0.92,
    }

    score, evidence = schema_candidate_score(
        field,
        relation,
        similarity=_similarity,
        context_score=_context_score,
    )

    assert evidence["unit_match"] is False
    assert evidence["exact_alias"] is True


def test_a_wrongly_aliased_field_no_longer_ties_the_correct_one_on_unit():
    """Reproduces the real production bug directly: alias-learning had (before
    a separate fix) let "ED Volume/BSA" leak into ES Volume's own alias list.
    Even with that alias contamination still in place, the correct field
    (whose unit genuinely matches) must score strictly higher than the
    wrongly-aliased one -- before this fix they scored identically (both
    "ml" and "ml/m2" registered as unit_match=True for a "ml/m2" value), so
    the greedy mapping's winner was decided by unrelated tie-break order
    instead of the actual unit.
    """
    relation = {
        "label_text": "ED Volume/BSA",
        "value_text": "93.1 ml/m²",
        "context_text": "Links",
        "relation_type": "table_cell",
        "confidence": 0.92,
    }
    correct_field = {
        "field_key": "lv_ed_volume_bsa",
        "display_name": "Left ventricle ED Volume/BSA",
        "group_name": "Left ventricle",
        "preferred_unit": "ml/m²",
        "aliases": ["ED Volume/BSA"],
    }
    wrongly_aliased_field = {
        "field_key": "lv_es_volume",
        "display_name": "Left ventricle ES Volume",
        "group_name": "Left ventricle",
        "preferred_unit": "ml",
        "aliases": ["ES Volume", "ED Volume/BSA"],
    }

    correct_score, correct_evidence = schema_candidate_score(
        correct_field, relation, similarity=_similarity, context_score=_context_score,
    )
    wrong_score, wrong_evidence = schema_candidate_score(
        wrongly_aliased_field, relation, similarity=_similarity, context_score=_context_score,
    )

    assert correct_evidence["unit_match"] is True
    assert wrong_evidence["unit_match"] is False
    assert correct_score > wrong_score


def test_compound_unit_still_matches_its_own_value():
    field = {
        "field_key": "lv_ed_volume_bsa",
        "display_name": "Left ventricle ED Volume/BSA",
        "group_name": "Left ventricle",
        "preferred_unit": "ml/m²",
        "aliases": ["ED Volume/BSA"],
    }
    relation = {
        "label_text": "ED Volume/BSA",
        "value_text": "93.1 ml/m²",
        "context_text": "Links",
        "relation_type": "table_cell",
        "confidence": 0.92,
    }

    score, evidence = schema_candidate_score(
        field,
        relation,
        similarity=_similarity,
        context_score=_context_score,
    )

    assert evidence["unit_match"] is True
    assert score >= 0.90


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


def test_bare_bsa_alias_does_not_match_an_unrelated_wall_mass_bsa_label():
    """Reproduces a real production bug directly: the bare "BSA" alias for
    ``study.bsa_m2`` was scoring ~0.82 against "ES Wall Mass/BSA" purely
    because ``_similarity``'s containment bonus gave any label ending in
    "/BSA" a high floor score, regardless of how much longer that label was
    than the bare alias. This caused one document's Body surface area field
    to read "92.7 gr/m²" -- the ES Wall Mass/BSA cell's own value and unit --
    instead of the real "1.98 m²" printed in the Study info line.

    ``dynamic_locator.py`` already guarded a related ED/ES/BSA mismatch; this
    guards the containment-bonus branch specifically (see that module's
    ``_similarity()`` NOTE for why the two fuzzy-matchers are not merged).
    """
    assert _similarity("BSA", "ES Wall Mass/BSA") < 0.5
    assert _similarity("BSA", "ED Wall + Papillary mass/BSA") < 0.5
    # A short label legitimately contained in a longer compound one (not a
    # bare ED/ES/BSA discriminator) must keep its existing high score.
    assert _similarity("ED Volume", "ED Volume/BSA") > 0.85
