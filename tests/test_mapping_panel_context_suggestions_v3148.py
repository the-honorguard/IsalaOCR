import json
from dataclasses import dataclass

from isala_ocr.models import Box
from isala_ocr.training.generic_detection import GenericRelation
from isala_ocr.training.mapping_ground_truth_fast import _enrich_relations_with_panel_context
from isala_ocr.training.mapping_lateral import (
    ambiguous_lateral_suffixes,
    lateral_candidate_allowed,
    relation_lateral_side,
)


@dataclass(frozen=True)
class _Table:
    table_id: str
    box: Box


def _write_gt(workspace):
    payload = {
        "schema_version": 1,
        "type": "canonical_table_cell_ground_truth",
        "revision": 1,
        "sources": {
            "source-1": {
                "source_id": "source-1",
                "review_completed": True,
                "cells": [
                    {
                        "gt_id": "lv-1",
                        "source_id": "source-1",
                        "panel_id": "lv",
                        "panel_name": "Left ventricle",
                        "x1": 10,
                        "y1": 10,
                        "x2": 110,
                        "y2": 40,
                    },
                    {
                        "gt_id": "lv-2",
                        "source_id": "source-1",
                        "panel_id": "lv",
                        "panel_name": "Left ventricle",
                        "x1": 10,
                        "y1": 45,
                        "x2": 110,
                        "y2": 75,
                    },
                    {
                        "gt_id": "rv-1",
                        "source_id": "source-1",
                        "panel_id": "rv",
                        "panel_name": "Right ventricle",
                        "x1": 210,
                        "y1": 10,
                        "x2": 310,
                        "y2": 40,
                    },
                    {
                        "gt_id": "rv-2",
                        "source_id": "source-1",
                        "panel_id": "rv",
                        "panel_name": "Right ventricle",
                        "x1": 210,
                        "y1": 45,
                        "x2": 310,
                        "y2": 75,
                    },
                ],
            }
        },
    }
    (workspace / "table_cell_ground_truth.json").write_text(json.dumps(payload), encoding="utf-8")


def _relation(relation_id, table_id):
    return GenericRelation(
        relation_id=relation_id,
        source_id="source-1",
        label_block_id=f"label-{relation_id}",
        value_block_id=f"value-{relation_id}",
        unit_block_id=None,
        relation_type="table_cell",
        confidence=0.99,
        rank=1,
        context_text="Endo Volume Normal Values Chuang",
        table_id=table_id,
        row_index=2,
        value_column_index=1,
    )


def test_canonical_panel_identity_becomes_mapping_context(tmp_path):
    _write_gt(tmp_path)
    tables = [
        _Table("table-lv", Box(10, 10, 110, 75)),
        _Table("table-rv", Box(210, 10, 310, 75)),
    ]
    relations = [
        _relation("lv-co", "table-lv"),
        _relation("rv-edv", "table-rv"),
    ]

    enriched, contexts = _enrich_relations_with_panel_context(
        tmp_path, "source-1", tables, relations
    )

    assert contexts["table-lv"] == "Left ventricle | lv"
    assert contexts["table-rv"] == "Right ventricle | rv"
    assert "Left ventricle | lv" in enriched[0].context_text
    assert "Right ventricle | rv" in enriched[1].context_text
    assert relation_lateral_side(enriched[0].as_dict()) == "left"
    assert relation_lateral_side(enriched[1].as_dict()) == "right"


def test_panel_context_allows_only_correct_bilateral_target(tmp_path):
    _write_gt(tmp_path)
    table = _Table("table-lv", Box(10, 10, 110, 75))
    relation = _relation("lv-edv", "table-lv")
    enriched, _ = _enrich_relations_with_panel_context(
        tmp_path, "source-1", [table], [relation]
    )
    relation_payload = enriched[0].as_dict()

    lv = {"field_key": "lv_ed_volume", "group_name": "Left ventricle"}
    rv = {"field_key": "rv_ed_volume", "group_name": "Right ventricle"}
    ambiguities = ambiguous_lateral_suffixes([lv, rv])

    assert "ed_volume" in ambiguities
    assert lateral_candidate_allowed(lv, relation_payload, ambiguities)
    assert not lateral_candidate_allowed(rv, relation_payload, ambiguities)
