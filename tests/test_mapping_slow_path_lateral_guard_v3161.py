"""``suggest_mappings`` (the non-``table_first`` strategy path) must apply the
same lateral-ambiguity guard and exact-alias disambiguation as
``suggest_mappings_fast``.

Before this fix, ``collector.py`` only used ``suggest_mappings_fast`` when
``strategy == "table_first"``; every other strategy (and the ROI mapping
studio / canonical ground-truth collection, which always call the plain
``suggest_mappings``) got the older scoring path without these guards, so a
bug fix in one path silently did not apply to the other. See
``documentation/CODE_REVIEW_v3.16.0.md`` ("Hoog" section) for the review that
flagged this drift.
"""

from __future__ import annotations

from typing import Any

from isala_ocr.training.mapping import suggest_mappings


class FakeTrainingDatabase:
    """Minimal stand-in for ``TrainingDatabase`` covering only what
    ``suggest_mappings`` reads and writes, so the scoring logic can be
    exercised without a real SQLite-backed project workspace.
    """

    def __init__(
        self,
        *,
        source: dict[str, Any],
        fields: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        blocks: dict[str, dict[str, Any]],
        annotations: list[dict[str, Any]],
    ) -> None:
        self._source = source
        self._fields = fields
        self._relations = relations
        self._blocks = blocks
        self._annotations = annotations
        self.upserted: list[dict[str, Any]] = []

    def clear_suggested_mappings(self, source_id: str) -> None:
        del source_id

    def list_detected_relations(self, source_id: str) -> list[dict[str, Any]]:
        del source_id
        return self._relations

    def get_detection_source(self, source_id: str) -> dict[str, Any] | None:
        del source_id
        return self._source

    def list_relation_feedback(self) -> list[dict[str, Any]]:
        return []

    def list_field_definitions(self, active_only: bool = True) -> list[dict[str, Any]]:
        del active_only
        return self._fields

    def list_mappings(self, source_id: str, status: str | None = None) -> list[dict[str, Any]]:
        del source_id
        if status is None:
            return []
        return []

    def list_detection_annotations(self, source_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        del source_id, active_only
        return self._annotations

    def list_detection_candidates(self, source_id: str) -> list[dict[str, Any]]:
        del source_id
        return []

    def get_detected_block(self, block_id: str) -> dict[str, Any] | None:
        return self._blocks.get(block_id)

    def upsert_mapping(self, **kwargs: Any) -> dict[str, Any]:
        record = dict(kwargs)
        record["mapping_id"] = f"map-{len(self.upserted)}"
        self.upserted.append(record)
        return record


def _value_block(block_id: str, x1: int, y1: int) -> dict[str, Any]:
    return {"block_id": block_id, "x1": x1, "y1": y1, "x2": x1 + 100, "y2": y1 + 20, "role": "value"}


def _reviewed_annotation(block: dict[str, Any]) -> dict[str, Any]:
    # An identical box gives full coverage/IoU so `_pipeline_a_geometry_match`
    # accepts it regardless of the guard behaviour under test.
    return {
        "annotation_id": f"ann-{block['block_id']}",
        "x1": block["x1"], "y1": block["y1"], "x2": block["x2"], "y2": block["y2"],
        "review_status": "reviewed",
    }


def _relation(relation_id: str, label: str, value_block_id: str, *, context: str = "", value_text: str = "80 ml") -> dict[str, Any]:
    return {
        "relation_id": relation_id,
        "label_text": label,
        "value_text": value_text,
        "context_text": context,
        "relation_type": "table_row",
        "confidence": 0.95,
        "rank": 1,
        "status": "proposed",
        "value_block_id": value_block_id,
        "label_block_id": "",
        "unit_block_id": "",
    }


def test_slow_path_does_not_auto_assign_ambiguous_bilateral_measurement() -> None:
    lv = {"field_key": "lv_ejection_fraction", "display_name": "Ejection Fraction", "group_name": "Left ventricle", "aliases": [], "preferred_unit": "%"}
    rv = {"field_key": "rv_ejection_fraction", "display_name": "Ejection Fraction", "group_name": "Right ventricle", "aliases": [], "preferred_unit": "%"}
    value_block = _value_block("value-ef", 100, 100)
    relation = _relation("rel-ef", "Ejection Fraction", "value-ef", context="", value_text="55 %")

    database = FakeTrainingDatabase(
        source={"source_id": "src", "image_width": 1000, "image_height": 1000},
        fields=[lv, rv],
        relations=[relation],
        blocks={"value-ef": value_block},
        annotations=[_reviewed_annotation(value_block)],
    )

    suggested = suggest_mappings(database, "src")

    # Without lateral evidence, neither ventricle side may claim the relation.
    assert suggested == []


def test_slow_path_keeps_distinct_exact_alias_fields_correctly_paired() -> None:
    """Sanity check for the exact-alias disambiguation pass ported from
    ``suggest_mappings_fast``: two same-unit, same-group fields with their own
    exact-alias relation must each keep their own match, not swap or drop one.
    """
    stroke_volume = {
        "field_key": "lv_stroke_volume", "display_name": "Stroke Volume",
        "group_name": "Left ventricle", "aliases": ["SV"], "preferred_unit": "ml",
    }
    ed_volume = {
        "field_key": "lv_ed_volume", "display_name": "ED Volume",
        "group_name": "Left ventricle", "aliases": ["ED-volume"], "preferred_unit": "ml",
    }
    sv_block = _value_block("value-sv", 100, 100)
    ed_block = _value_block("value-ed", 100, 140)
    relations = [
        _relation("rel-sv", "Stroke Volume", "value-sv", context="Left ventricle", value_text="80 ml"),
        _relation("rel-ed", "ED Volume", "value-ed", context="Left ventricle", value_text="150 ml"),
    ]

    database = FakeTrainingDatabase(
        source={"source_id": "src", "image_width": 1000, "image_height": 1000},
        fields=[stroke_volume, ed_volume],
        relations=relations,
        blocks={"value-sv": sv_block, "value-ed": ed_block},
        annotations=[_reviewed_annotation(sv_block), _reviewed_annotation(ed_block)],
    )

    suggested = suggest_mappings(database, "src")

    by_field = {item["field_key"]: item["relation_id"] for item in suggested}
    assert by_field.get("lv_stroke_volume") == "rel-sv"
    assert by_field.get("lv_ed_volume") == "rel-ed"


def test_slow_path_source_now_carries_the_same_guards_as_the_fast_path() -> None:
    """Guard against this exact drift recurring: both mapping strategies must
    keep applying the lateral guard and exact-alias disambiguation, not just
    whichever one a future change happens to touch.
    """
    import inspect

    from isala_ocr.training import mapping

    source = inspect.getsource(mapping.suggest_mappings)
    assert "ambiguous_lateral_suffixes(fields)" in source
    assert "lateral_candidate_allowed(field, relation, lateral_ambiguities)" in source
    assert "exact_candidates" in source and "exact_assignments" in source
