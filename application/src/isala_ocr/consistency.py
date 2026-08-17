from __future__ import annotations

from .config import ConsistencyRuleSpec
from .models import ConsistencyResult, FieldResult


def evaluate_consistency(
    fields: list[FieldResult],
    rules: list[ConsistencyRuleSpec],
) -> list[ConsistencyResult]:
    indexed = {field.key: field for field in fields}
    results: list[ConsistencyResult] = []

    for rule in rules:
        target = indexed[rule.target]
        left = indexed[rule.left]
        right = indexed[rule.right]
        involved = [rule.target, rule.left, rule.right]
        if any(item.value is None or not item.valid for item in (target, left, right)):
            results.append(
                ConsistencyResult(
                    name=rule.name,
                    kind=rule.kind,
                    passed=None,
                    observed=target.value,
                    expected=None,
                    absolute_delta=None,
                    tolerance=None,
                    fields=involved,
                    reason="one_or_more_fields_invalid",
                )
            )
            continue

        assert target.value is not None and left.value is not None and right.value is not None
        if rule.kind == "sum":
            expected = left.value + right.value
        elif rule.kind == "difference":
            expected = left.value - right.value
        elif rule.kind == "ratio_percent":
            if right.value == 0:
                results.append(
                    ConsistencyResult(
                        name=rule.name,
                        kind=rule.kind,
                        passed=None,
                        observed=target.value,
                        expected=None,
                        absolute_delta=None,
                        tolerance=None,
                        fields=involved,
                        reason="division_by_zero",
                    )
                )
                continue
            expected = 100.0 * left.value / right.value
        else:  # Configuration validation prevents this.
            raise ValueError(f"Unsupported consistency rule: {rule.kind}")

        delta = abs(target.value - expected)
        tolerance = max(rule.absolute_tolerance, abs(expected) * rule.relative_tolerance)
        results.append(
            ConsistencyResult(
                name=rule.name,
                kind=rule.kind,
                passed=delta <= tolerance,
                observed=round(target.value, 4),
                expected=round(expected, 4),
                absolute_delta=round(delta, 4),
                tolerance=round(tolerance, 4),
                fields=involved,
                reason=None if delta <= tolerance else "outside_tolerance",
            )
        )
    return results
