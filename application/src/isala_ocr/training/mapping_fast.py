from __future__ import annotations

from typing import Any

from .db import TrainingDatabase
from .generic_detection import normalize_text
from .mapping import (
    _block_box,
    _context_score,
    _pipeline_a_geometry_match,
    _similarity,
    _unique,
)
from .relation_feedback import evaluate_feedback, relation_snapshot


def suggest_mappings_fast(
    database: TrainingDatabase,
    source_id: str,
    *,
    minimum_score: float = 0.68,
    profile_id: str = "",
) -> list[dict[str, Any]]:
    """Suggest mappings without N+1 SQLite geometry lookups.

    The original suggestion path resolved the same value block and Pipeline-A
    geometry again for every field/relation pair. On a Windows/Docker bind mount
    that means thousands of SQLite connections for one source. This version
    loads the source graph once, resolves each unique value geometry once, and
    writes the selected suggestions in one transaction while preserving the
    existing scoring and validation semantics.
    """
    database.clear_suggested_mappings(source_id)
    relations = database.list_detected_relations(source_id)
    source = database.get_detection_source(source_id) or {"source_id": source_id}
    source_width = int(source.get("image_width") or 0)
    source_height = int(source.get("image_height") or 0)
    if source_width <= 0 or source_height <= 0:
        return []

    feedback_examples = database.list_relation_feedback()
    feedback_by_relation = {
        str(relation["relation_id"]): evaluate_feedback(
            relation_snapshot(relation, source), feedback_examples
        )
        for relation in relations
        if str(relation.get("status") or "proposed") != "rejected"
    }
    fields = database.list_field_definitions(active_only=True)
    existing = database.list_mappings(source_id)
    confirmed_fields = {
        str(item["field_key"])
        for item in existing
        if str(item.get("status") or "") == "confirmed"
    }
    confirmed_relations = {
        str(item["relation_id"])
        for item in existing
        if str(item.get("status") or "") == "confirmed" and str(item.get("relation_id") or "")
    }

    # One read per source, not one read per field x relation pair.
    blocks_by_id = {
        str(item["block_id"]): item
        for item in database.list_detected_blocks(source_id, semantic_only=True)
    }
    annotations = database.list_detection_annotations(source_id, active_only=True)
    candidates = database.list_detection_candidates(source_id)

    geometry_by_value: dict[str, object | None] = {}
    eligible_relations: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for relation in relations:
        relation_id = str(relation.get("relation_id") or "")
        if relation_id in confirmed_relations:
            continue
        if str(relation.get("status") or "proposed") == "rejected":
            continue
        if int(relation.get("rank") or 1) != 1:
            continue
        feedback = feedback_by_relation.get(relation_id)
        if feedback is None or feedback["hard_reject"]:
            continue
        label = str(relation.get("label_text") or "")
        if not label:
            continue
        value_block_id = str(relation.get("value_block_id") or "")
        value_block = blocks_by_id.get(value_block_id)
        if value_block is None:
            continue
        if value_block_id not in geometry_by_value:
            geometry_by_value[value_block_id] = _pipeline_a_geometry_match(
                database,
                source_id,
                _block_box(value_block).clamp(source_width, source_height),
                source_width,
                source_height,
                annotations=annotations,
                candidates=candidates,
            )
        if geometry_by_value[value_block_id] is None:
            continue
        eligible_relations.append((relation, feedback))

    suggestions: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for field in fields:
        field_key = str(field.get("field_key") or "")
        if field_key in confirmed_fields:
            continue
        aliases = _unique([str(field.get("display_name") or ""), *field.get("aliases", [])])
        for relation, feedback in eligible_relations:
            label = str(relation.get("label_text") or "")
            label_score = max((_similarity(label, alias) for alias in aliases), default=0.0)
            context = str(relation.get("context_text") or "")
            context_value = _context_score(str(field.get("group_name") or ""), context)
            unit = normalize_text(str(field.get("preferred_unit") or ""))
            value_text = normalize_text(str(relation.get("value_text") or ""))
            unit_bonus = 0.08 if unit and unit in value_text else 0.0
            table_bonus = 0.10 if str(relation.get("relation_type") or "").startswith("table_") else 0.0
            score = 0.74 * label_score + 0.12 * max(-1.0, context_value) + unit_bonus + table_bonus
            score *= 0.76 + 0.24 * float(relation.get("confidence") or 0)
            score *= float(feedback["multiplier"])
            if score < minimum_score:
                continue
            relation_with_feedback = dict(relation)
            relation_with_feedback["feedback_quality"] = float(feedback["quality"])
            relation_with_feedback["feedback_matched_examples"] = int(feedback["matched_examples"])
            suggestions.append((score, field, relation_with_feedback))

    suggestions.sort(key=lambda item: item[0], reverse=True)
    used_fields = set(confirmed_fields)
    used_relations = set(confirmed_relations)
    stored_ids: list[str] = []
    # Store all suggestions in one SQLite transaction. The regular public
    # upsert_mapping method opens a new connection for every item.
    with database.connect() as db:
        for score, field, relation in suggestions:
            field_key = str(field["field_key"])
            relation_id = str(relation["relation_id"])
            if field_key in used_fields or relation_id in used_relations:
                continue
            mapping_id = database._upsert_mapping_in_connection(
                db,
                source_id=source_id,
                field_key=field_key,
                relation_id=relation_id,
                label_block_id=str(relation.get("label_block_id") or ""),
                value_block_id=str(relation["value_block_id"]),
                unit_block_id=str(relation.get("unit_block_id") or ""),
                status="suggested",
                mapping_confidence=score,
                notes=(
                    "automatic alias/context suggestion"
                    + (
                        f"; feedback_examples={int(relation.get('feedback_matched_examples') or 0)}"
                        if int(relation.get("feedback_matched_examples") or 0)
                        else ""
                    )
                ),
                profile_id=profile_id,
            )
            stored_ids.append(mapping_id)
            used_fields.add(field_key)
            used_relations.add(relation_id)

    if not stored_ids:
        return []
    by_id = {
        str(item["mapping_id"]): item
        for item in database.list_mappings(source_id)
        if str(item.get("mapping_id") or "") in set(stored_ids)
    }
    return [by_id[mapping_id] for mapping_id in stored_ids if mapping_id in by_id]
