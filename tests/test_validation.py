from isala_ocr.config import FieldSpec
from isala_ocr.models import Box
from isala_ocr.validation import evaluate_candidate, parse_value


def spec(**overrides):
    values = dict(
        key="test",
        label="Test",
        roi=Box(0, 0, 10, 10),
        unit="ml",
        minimum=0.0,
        maximum=300.0,
        decimals=1,
        allow_missing=False,
        whitelist=None,
    )
    values.update(overrides)
    return FieldSpec(**values)


def test_parse_decimal_comma():
    parsed = parse_value("128,7 ml", "ml")
    assert parsed.value == 128.7


def test_infers_dropped_decimal_only_when_range_requires_it():
    result = evaluate_candidate(spec(maximum=100.0), "test", "643 ml", 0.9)
    assert result.valid is True
    assert result.value == 64.3
    assert any(item.startswith("inferred_decimal") for item in result.corrections)


def test_does_not_change_valid_integer():
    result = evaluate_candidate(spec(maximum=300.0), "test", "128 ml", 0.9)
    assert result.value == 128.0
    assert result.corrections == []


def test_missing_dash_allowed():
    result = evaluate_candidate(spec(allow_missing=True, unit="g"), "shape", "-", 0.8)
    assert result.valid is True
    assert result.value is None


def test_out_of_range_rejected_when_decimal_inference_cannot_fix_it():
    result = evaluate_candidate(spec(maximum=10.0, decimals=1), "test", "9999 ml", 0.9)
    assert result.valid is False
    assert result.reason == "above_maximum:10.0"
