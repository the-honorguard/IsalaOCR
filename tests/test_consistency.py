from isala_ocr.config import ConsistencyRuleSpec
from isala_ocr.consistency import evaluate_consistency
from isala_ocr.models import Box, FieldResult


def field(key: str, value: float) -> FieldResult:
    return FieldResult(
        key=key,
        label=key,
        raw_text=str(value),
        value=value,
        unit="ml",
        confidence=0.9,
        valid=True,
        reason=None,
        roi=Box(0, 0, 10, 10),
        variant="fake",
    )


def test_difference_rule_passes():
    fields = [field("ed", 128.7), field("es", 61.6), field("sv", 67.1)]
    rules = [
        ConsistencyRuleSpec(
            name="sv_check",
            kind="difference",
            target="sv",
            left="ed",
            right="es",
            absolute_tolerance=2.0,
            relative_tolerance=0.05,
        )
    ]
    result = evaluate_consistency(fields, rules)[0]
    assert result.passed is True
    assert result.absolute_delta == 0.0


def test_ratio_rule_catches_missing_leading_digit():
    fields = [field("ed", 11.2), field("sv", 64.3), field("ef", 58.0)]
    rules = [
        ConsistencyRuleSpec(
            name="ef_check",
            kind="ratio_percent",
            target="ef",
            left="sv",
            right="ed",
            absolute_tolerance=5.0,
            relative_tolerance=0.08,
        )
    ]
    result = evaluate_consistency(fields, rules)[0]
    assert result.passed is False
    assert result.expected > 500
