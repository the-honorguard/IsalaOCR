from __future__ import annotations

from pathlib import Path
from typing import Any

from .db import TrainingDatabase
from .mapping import (
    _context_score,
    _similarity,
)
from .mapping_lateral import ambiguous_lateral_suffixes, lateral_candidate_allowed
from .mapping_semantics import schema_candidate_score
from .recognition_ground_truth import relation_column_eligible, table_studio_roles
from .relation_feedback import evaluate_feedback, relation_snapshot
from .table_panels import load_panel_profile


def _geometry_looks_sane(block: dict[str, Any], image_width: int, image_height: int) -> bool:
    """Reject a value block whose box is obviously broken.

    This is not a Pipeline-A overlap check (deliberately deferred to
    materialization, see the docstring below) -- it is a cheap, local
    bounds check using data already loaded for this source, so a corrupt
    detection (a degenerate or out-of-frame box, for example from a table
    detector regression) cannot silently turn into a mapping suggestion
    before anyone reviews it.
    """
    try:
        x1, y1, x2, y2 = (int(block[key]) for key in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        return False
    if x2 <= x1 or y2 <= y1:
        return False
    return x1 >= 0 and y1 >= 0 and x2 <= image_width and y2 <= image_height


def suggest_mappings_fast(
    database: TrainingDatabase,
    source_id: str,
    *,
    minimum_score: float = 0.68,
    auto_confirm_score: float = 0.90,
    profile_id: str = "",
    workspace: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Suggest mappings without N+1 SQLite geometry lookups.

    Mapping is label/table driven: the relation already identifies the value
    cell in the same table row and value column as the readable label. Pipeline-
    A ROI validation is deliberately deferred to value materialization; a light
    local sanity check on the value block's own box (``_geometry_looks_sane``)
    still runs here, so an evidently broken detection cannot become a
    suggestion before that later validation ever sees it.

    Semantic matching is schema-driven: aliases, preferred unit, optional group
    context, relation type and OCR confidence are the only positive evidence.
    The engine contains no report- or field-name-specific rules.

    Bilateral measurements remain conservative: when both lateral targets exist
    for the same metric, a generic relation needs explicit left/right evidence
    before it may become an automatic suggestion.

    A candidate scoring at or above ``auto_confirm_score`` is stored already
    ``confirmed`` instead of ``suggested``: correctness is checked again when
    the mapped value is delivered downstream, so a near-certain schema match
    does not need to wait on a manual click in Mapping Studio as well.

    ``workspace``, when given, applies Table Studio's per-panel column-role
    configuration as a hard eligibility gate before scoring -- see
    ``mapping.suggest_mappings``'s docstring for the same rule; both functions
    share ``recognition_ground_truth.relation_column_eligible`` so a column an
    operator marked "Overslaan" is excluded consistently regardless of which
    of the two suggestion engines a given run uses.
    """
    # Suggestions are generated from the current label/table graph only.
    database.clear_suggested_mappings(source_id)
    relations = database.list_detected_relations(source_id)
    source = database.get_detection_source(source_id) or {"source_id": source_id}
    source_width = int(source.get("image_width") or 0)
    source_height = int(source.get("image_height") or 0)
    if source_width <= 0 or source_height <= 0:
        return []
    panel_by_id: dict[str, dict[str, Any]] = {}
    column_roles: dict[str, dict[str, str]] = {}
    if workspace is not None:
        panel_profile = load_panel_profile(workspace)
        panel_by_id = {
            str(panel.get("panel_id") or ""): panel
            for panel in panel_profile.get("panels") or []
            if str(panel.get("panel_id") or "")
        }
        column_roles = table_studio_roles(workspace)

    feedback_examples = database.list_relation_feedback()
    feedback_by_relation = {
        str(relation["relation_id"]): evaluate_feedback(
            relation_snapshot(relation, source), feedback_examples
        )
        for relation in relations
        if str(relation.get("status") or "proposed") != "rejected"
    }
    fields = database.list_field_definitions(active_only=True)
    lateral_ambiguities = ambiguous_lateral_suffixes(fields)
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
        if not _geometry_looks_sane(value_block, source_width, source_height):
            continue
        if workspace is not None and not relation_column_eligible(
            relation, panel_by_id=panel_by_id, column_roles=column_roles
        ):
            continue
        # The value cell is selected by the table relation (same row and
        # value column). Pipeline-A ROI validation belongs to materialization,
        # not to deciding which field a readable label represents -- but an
        # evidently broken box (out of frame, zero/negative area) is rejected
        # here regardless, since no downstream step re-checks this before it
        # becomes a mapping suggestion.
        eligible_relations.append((relation, feedback))

    # The global field profile is authoritative when a label is an exact alias
    # in the correct table context. Without this pass, the later global score
    # sort can assign a same-unit field to the wrong row (for example Stroke
    # Volume -> ED Volume) simply because the labels are spatially duplicated.
    exact_candidates: dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]] = {}
    for relation, feedback in eligible_relations:
        relation_id = str(relation.get("relation_id") or "")
        for field in fields:
            field_key = str(field.get("field_key") or "")
            if field_key in confirmed_fields:
                continue
            if not lateral_candidate_allowed(field, relation, lateral_ambiguities):
                continue
            score, evidence = schema_candidate_score(
                field,
                relation,
                similarity=_similarity,
                context_score=_context_score,
                feedback_multiplier=float(feedback["multiplier"]),
            )
            if not evidence.get("exact_alias") or score < minimum_score:
                continue
            group = str(field.get("group_name") or "")
            context = str(relation.get("context_text") or "")
            context_value = _context_score(group, context)
            if group and context_value < 0:
                continue
            exact_candidates.setdefault(relation_id, []).append((score, field, {
                **dict(relation),
                "feedback_quality": float(feedback["quality"]),
                "feedback_matched_examples": int(feedback["matched_examples"]),
                "mapping_evidence": evidence,
            }))

    exact_assignments: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
    exact_field_use: dict[str, int] = {}
    for relation_id, candidates in exact_candidates.items():
        # An exact alias is safe only when the table context leaves one field
        # and that field is not claimed by another exact relation.
        field_keys = {str(item[1].get("field_key") or "") for item in candidates}
        if len(field_keys) == 1 and len(candidates) == 1:
            exact_assignments[relation_id] = candidates[0]
            field_key = next(iter(field_keys))
            exact_field_use[field_key] = exact_field_use.get(field_key, 0) + 1
    exact_assignments = {
        relation_id: item
        for relation_id, item in exact_assignments.items()
        if exact_field_use.get(str(item[1].get("field_key") or ""), 0) == 1
    }

    suggestions: list[tuple[float, dict[str, Any], dict[str, Any]]] = list(exact_assignments.values())
    for field in fields:
        field_key = str(field.get("field_key") or "")
        if field_key in confirmed_fields:
            continue
        for relation, feedback in eligible_relations:
            if str(relation.get("relation_id") or "") in exact_assignments:
                continue
            if not lateral_candidate_allowed(field, relation, lateral_ambiguities):
                continue
            score, evidence = schema_candidate_score(
                field,
                relation,
                similarity=_similarity,
                context_score=_context_score,
                feedback_multiplier=float(feedback["multiplier"]),
            )
            if score < minimum_score:
                continue
            relation_with_feedback = dict(relation)
            relation_with_feedback["feedback_quality"] = float(feedback["quality"])
            relation_with_feedback["feedback_matched_examples"] = int(feedback["matched_examples"])
            relation_with_feedback["mapping_evidence"] = evidence
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
            evidence = dict(relation.get("mapping_evidence") or {})
            evidence_notes = []
            if evidence.get("exact_alias"):
                evidence_notes.append("exact_alias")
            if evidence.get("unit_match"):
                evidence_notes.append("unit_match")
            if evidence.get("missing_value"):
                evidence_notes.append("missing_value")
            auto_confirmed = score >= auto_confirm_score
            mapping_id = database._upsert_mapping_in_connection(
                db,
                source_id=source_id,
                field_key=field_key,
                relation_id=relation_id,
                label_block_id=str(relation.get("label_block_id") or ""),
                value_block_id=str(relation["value_block_id"]),
                unit_block_id=str(relation.get("unit_block_id") or ""),
                status="confirmed" if auto_confirmed else "suggested",
                mapping_confidence=score,
                notes=(
                    "automatic schema suggestion"
                    + (f"; evidence={','.join(evidence_notes)}" if evidence_notes else "")
                    + (
                        f"; feedback_examples={int(relation.get('feedback_matched_examples') or 0)}"
                        if int(relation.get("feedback_matched_examples") or 0)
                        else ""
                    )
                    + (f"; auto_confirmed(score={score:.2f})" if auto_confirmed else "")
                ),
                profile_id=profile_id,
            )
            stored_ids.append(mapping_id)
            used_fields.add(field_key)
            used_relations.add(relation_id)

    if not stored_ids:
        return []
    stored_id_set = set(stored_ids)
    by_id = {
        str(item["mapping_id"]): item
        for item in database.list_mappings(source_id)
        if str(item.get("mapping_id") or "") in stored_id_set
    }
    return [by_id[mapping_id] for mapping_id in stored_ids if mapping_id in by_id]
