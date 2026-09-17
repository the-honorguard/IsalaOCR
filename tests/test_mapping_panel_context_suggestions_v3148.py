from dataclasses import dataclass

from isala_ocr.models import Box
from isala_ocr.training.generic_detection import GenericRelation
from isala_ocr.training.mapping_ground_truth_fast import (
    _enrich_relations_with_panel_context,
)
from isala_ocr.training.mapping_lateral import (
    ambiguous_lateral_suffixes,
    lateral_candidate_allowed,
    relation_lateral_side,
)
from isala_ocr.training.recognition_ground_truth import relation_panel_id
from isala_ocr.training.table_panels import (
    load_panel_profile,
    panel_boxes_for_image,
    save_panel_profile,
)

IMAGE_WIDTH = 320
IMAGE_HEIGHT = 100


@dataclass(frozen=True)
class _Table:
    table_id: str
    box: Box


def _write_panels(workspace):
    # Panel identity comes from Table/Panel Setup's own profile, not from
    # canonical GT cells (GT Studio review never records panel_id/panel_name
    # on a cell - see _configured_panel_regions()'s docstring). Boxes here
    # cover the same pixel regions the LV/RV table fixtures below occupy.
    save_panel_profile(
        workspace,
        panels=[
            {"panel_id": "lv", "name": "Left ventricle", "x1": 10 / IMAGE_WIDTH, "y1": 10 / IMAGE_HEIGHT, "x2": 110 / IMAGE_WIDTH, "y2": 75 / IMAGE_HEIGHT},
            {"panel_id": "rv", "name": "Right ventricle", "x1": 210 / IMAGE_WIDTH, "y1": 10 / IMAGE_HEIGHT, "x2": 310 / IMAGE_WIDTH, "y2": 75 / IMAGE_HEIGHT},
        ],
        reference_source_id="source-1",
        reference_width=IMAGE_WIDTH,
        reference_height=IMAGE_HEIGHT,
    )


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
    _write_panels(tmp_path)
    tables = [
        _Table("table-lv", Box(10, 10, 110, 75)),
        _Table("table-rv", Box(210, 10, 310, 75)),
    ]
    relations = [
        _relation("lv-co", "table-lv"),
        _relation("rv-edv", "table-rv"),
    ]

    enriched, contexts = _enrich_relations_with_panel_context(
        tmp_path, IMAGE_WIDTH, IMAGE_HEIGHT, tables, relations
    )

    assert contexts["table-lv"] == "Left ventricle | lv"
    assert contexts["table-rv"] == "Right ventricle | rv"
    assert "Left ventricle | lv" in enriched[0].context_text
    assert "Right ventricle | rv" in enriched[1].context_text
    assert relation_lateral_side(enriched[0].as_dict()) == "left"
    assert relation_lateral_side(enriched[1].as_dict()) == "right"


def test_panel_context_allows_only_correct_bilateral_target(tmp_path):
    _write_panels(tmp_path)
    table = _Table("table-lv", Box(10, 10, 110, 75))
    relation = _relation("lv-edv", "table-lv")
    enriched, _ = _enrich_relations_with_panel_context(
        tmp_path, IMAGE_WIDTH, IMAGE_HEIGHT, [table], [relation]
    )
    relation_payload = enriched[0].as_dict()

    lv = {"field_key": "lv_ed_volume", "group_name": "Left ventricle"}
    rv = {"field_key": "rv_ed_volume", "group_name": "Right ventricle"}
    ambiguities = ambiguous_lateral_suffixes([lv, rv])

    assert "ed_volume" in ambiguities
    assert lateral_candidate_allowed(lv, relation_payload, ambiguities)
    assert not lateral_candidate_allowed(rv, relation_payload, ambiguities)


def test_reconfigured_panel_replaces_stale_identity_instead_of_accumulating(tmp_path):
    """Editing Table/Panel Setup must not leave a table's old panel identity behind.

    If a table moves from one configured panel to another while both panels
    still exist, appending the fresh identity without removing the stale one
    left context_text carrying both - and relation_panel_id() (which just
    scans context_text for any known panel token) could keep resolving to
    the old, now-wrong panel depending on token order, silently applying
    that panel's Table Studio column roles and lateral side forever.
    """
    _write_panels(tmp_path)
    table = _Table("table-a", Box(10, 10, 110, 75))
    relation = _relation("moved", "table-a")

    enriched_once, _ = _enrich_relations_with_panel_context(
        tmp_path, IMAGE_WIDTH, IMAGE_HEIGHT, [table], [relation]
    )
    assert "Left ventricle | lv" in enriched_once[0].context_text

    # Table/Panel Setup gets edited: this same table position now belongs to
    # "Rechts"/rv instead (panels swap which box they cover).
    save_panel_profile(
        tmp_path,
        panels=[
            {"panel_id": "lv", "name": "Left ventricle", "x1": 210 / IMAGE_WIDTH, "y1": 10 / IMAGE_HEIGHT, "x2": 310 / IMAGE_WIDTH, "y2": 75 / IMAGE_HEIGHT},
            {"panel_id": "rv", "name": "Right ventricle", "x1": 10 / IMAGE_WIDTH, "y1": 10 / IMAGE_HEIGHT, "x2": 110 / IMAGE_WIDTH, "y2": 75 / IMAGE_HEIGHT},
        ],
        reference_source_id="source-1",
        reference_width=IMAGE_WIDTH,
        reference_height=IMAGE_HEIGHT,
    )

    enriched_twice, contexts = _enrich_relations_with_panel_context(
        tmp_path, IMAGE_WIDTH, IMAGE_HEIGHT, [table], [enriched_once[0]]
    )
    refreshed_context = enriched_twice[0].context_text

    assert contexts["table-a"] == "Right ventricle | rv"
    assert "Right ventricle | rv" in refreshed_context
    assert "lv" not in refreshed_context.casefold()
    assert "left ventricle" not in refreshed_context.casefold()

    panel_by_id = {
        str(item["panel_id"]): item
        for item in panel_boxes_for_image(load_panel_profile(tmp_path), IMAGE_WIDTH, IMAGE_HEIGHT)
    }
    assert relation_panel_id({"context_text": refreshed_context}, panel_by_id) == "rv"
