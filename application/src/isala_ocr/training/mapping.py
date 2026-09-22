from __future__ import annotations

import hashlib
import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from ..geometry import area as _area
from ..geometry import intersection_area as _intersection_area
from ..models import Box

if TYPE_CHECKING:
    from ..config import AppConfig, Profile
    from ..ocr.base import OCREngine
from .db import TrainingDatabase, utc_now
from .generic_detection import normalize_text
from .projects import resolve_project_workspace
from .mapping_lateral import ambiguous_lateral_suffixes, lateral_candidate_allowed
from .mapping_semantics import is_missing_value_text, schema_candidate_score
from .relation_feedback import evaluate_feedback, relation_snapshot

LOGGER = logging.getLogger(__name__)
MAPPING_ENGINE_VERSION = "generic-mapping-v4-schema-evidence"


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        normalized = normalize_text(text)
        if text and normalized and normalized not in seen:
            seen.add(normalized)
            result.append(text)
    return result


def default_field_definitions(profile: Profile) -> list[dict[str, Any]]:
    """Build an editable field schema without coupling the detector to it."""
    definitions: list[dict[str, Any]] = []
    legacy_aliases = {
        "ed_volume": ["ED-volume", "ED volume", "Einddiastolisch volume"],
        "es_volume": ["ES-volume", "ES volume", "Eindsystolisch volume"],
        "ejection_fraction": ["Ejectiefractie", "EF"],
        "stroke_volume": ["Slagvolume", "SV"],
        "cardiac_output": ["Hartminuutvolume", "Cardiac output", "CO"],
        "ed_volume_bsa": ["ED-volume/BSA", "ED volume/BSA"],
        "es_volume_bsa": ["ES-volume/BSA", "ES volume/BSA"],
        "ed_wall_mass": ["ED-wandmassa", "ED wall mass"],
    }
    for field in profile.fields:
        group = {
            "lv": "Left ventricle",
            "rv": "Right ventricle",
        }.get(str(field.panel or "").casefold(), str(field.panel or ""))
        suffix = str(field.key or "").removeprefix("lv_").removeprefix("rv_")
        aliases = _unique([field.label, *field.screen_labels, *legacy_aliases.get(suffix, [])])
        definitions.append(
            {
                "field_key": field.key,
                "display_name": field.label,
                "group_name": group,
                "data_type": "decimal",
                "preferred_unit": field.unit or "",
                "aliases": aliases,
                "minimum_value": field.minimum,
                "maximum_value": field.maximum,
                "required": not field.allow_missing,
                "built_in": True,
            }
        )

    # Additional common fields are schema data only. The generic detector has no
    # knowledge of these names and will still detect arbitrary labels/values.
    common_measurements = [
        ("stroke_index", "Stroke Index", "Slagindex", "ml/m²"),
        ("cardiac_index", "Cardiac Index", "Hartindex", "L/(min·m²)"),
        ("cardiac_density", "Cardiac Density", "Cardiale densiteit", "g/ml"),
        ("ed_wall_mass_bsa", "ED Wall Mass/BSA", "ED-wandmassa/BSA", "g/m²"),
        ("ed_wall_papillary_mass", "ED Wall + Papillary Mass", "ED-wand + papillairspiermassa", "g"),
        ("ed_wall_papillary_mass_bsa", "ED Wall + Papillary Mass/BSA", "ED-wand + papillairspiermassa/BSA", "g/m²"),
    ]
    existing = {item["field_key"] for item in definitions}
    for prefix, group in (("lv", "Left ventricle"), ("rv", "Right ventricle")):
        for suffix, english, dutch, unit in common_measurements:
            key = f"{prefix}_{suffix}"
            if key in existing:
                continue
            definitions.append(
                {
                    "field_key": key,
                    "display_name": f"{group} {english}",
                    "group_name": group,
                    "data_type": "decimal",
                    "preferred_unit": unit,
                    "aliases": _unique([english, dutch]),
                    "minimum_value": None,
                    "maximum_value": None,
                    "required": False,
                    "built_in": True,
                }
            )

    definitions.extend(
        [
            {
                "field_key": "study.heart_rate_bpm",
                "display_name": "Heart rate",
                "group_name": "Study information",
                "data_type": "integer",
                "preferred_unit": "bpm",
                "aliases": ["HR", "Heart rate", "Hartfrequentie"],
                "minimum_value": 20,
                "maximum_value": 250,
                "required": False,
                "built_in": True,
            },
            {
                "field_key": "study.bsa_m2",
                "display_name": "Body surface area",
                "group_name": "Study information",
                "data_type": "decimal",
                "preferred_unit": "m²",
                "aliases": ["BSA", "Body surface area", "Lichaamsoppervlak"],
                "minimum_value": 0.2,
                "maximum_value": 4.0,
                "required": False,
                "built_in": True,
            },
            {
                "field_key": "study.height_m",
                "display_name": "Height",
                "group_name": "Study information",
                "data_type": "decimal",
                "preferred_unit": "m",
                "aliases": ["Height", "Length", "Lengte"],
                "minimum_value": 0.3,
                "maximum_value": 2.7,
                "required": False,
                "built_in": True,
            },
            {
                "field_key": "study.weight_kg",
                "display_name": "Weight",
                "group_name": "Study information",
                "data_type": "decimal",
                "preferred_unit": "kg",
                "aliases": ["Weight", "Gewicht"],
                "minimum_value": 1,
                "maximum_value": 500,
                "required": False,
                "built_in": True,
            },
            {
                "field_key": "study.gender",
                "display_name": "Gender",
                "group_name": "Study information",
                "data_type": "code",
                "preferred_unit": "",
                "aliases": ["Gender", "Sex", "Geslacht"],
                "minimum_value": None,
                "maximum_value": None,
                "required": False,
                "built_in": True,
            },
        ]
    )
    return definitions


def ensure_default_field_definitions(database: TrainingDatabase, profile: Profile) -> int:
    return database.seed_field_definitions(default_field_definitions(profile))


def _similarity(left: str, right: str) -> float:
    """Fuzzy-match a schema-candidate label against a field label during Mapping.

    NOTE: ``dynamic_locator.py`` has its own, differently-tuned
    ``_similarity()`` for a different problem (locator-label vs. OCR-observed
    text matching, normalized with ``normalize_for_matching()`` instead of
    this module's ``normalize_text()``, with ED/ES/BSA domain guards this one
    doesn't have). They are NOT merged (CODE_REVIEW_v3.16.0.md, sectie Hoog;
    zie ook documentation/architecture/refactor-phase2-plan.md, item 4): if
    Mapping ever needs the same ED/ES/BSA protection dynamic_locator.py has,
    port the guard deliberately -- don't unify the two functions wholesale,
    that would shift real field-matching behavior in production with no way
    to verify the shift is safe across the full range of real reports.
    """
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        containment = min(len(a), len(b)) / max(len(a), len(b))
        return 0.78 + 0.20 * containment
    return SequenceMatcher(None, a, b).ratio()


def _context_score(group_name: str, context_text: str) -> float:
    group = normalize_text(group_name)
    context = normalize_text(context_text)
    if not group or not context:
        return 0.0
    left_terms = {"left", "links", "linker", "linkerventrikel", "lv"}
    right_terms = {"right", "rechts", "rechter", "rechterventrikel", "rv"}
    group_tokens = set(group.split())
    context_tokens = set(context.split())
    if group_tokens & left_terms:
        if context_tokens & left_terms:
            return 1.0
        if context_tokens & right_terms:
            return -1.0
    if group_tokens & right_terms:
        if context_tokens & right_terms:
            return 1.0
        if context_tokens & left_terms:
            return -1.0
    return _similarity(group, context) * 0.5


def suggest_mappings(
    database: TrainingDatabase,
    source_id: str,
    *,
    minimum_score: float = 0.68,
    profile_id: str = "",
) -> list[dict[str, Any]]:
    """Create non-destructive suggestions from neutral relations and schema metadata."""
    database.clear_suggested_mappings(source_id)
    relations = database.list_detected_relations(source_id)
    source = database.get_detection_source(source_id) or {"source_id": source_id}
    source_width = int(source.get("image_width") or 0)
    source_height = int(source.get("image_height") or 0)
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
    confirmed_fields = {item["field_key"] for item in existing if item["status"] == "confirmed"}
    confirmed_relations = {item["relation_id"] for item in existing if item["status"] == "confirmed" and item["relation_id"]}

    # Everything below is per-relation, not per-(field, relation): checking it
    # inside the `for field in fields` loop repeated the same
    # get_detected_block() + Pipeline-A geometry lookup (each its own database
    # round-trip) once per field for every relation, an O(fields x relations)
    # cost for a property that never depends on which field is being scored.
    # Pre-fetch each source's annotations/candidates once and reuse them
    # across every relation instead of re-querying per relation too.
    source_annotations = database.list_detection_annotations(source_id, active_only=True) if source_width > 0 and source_height > 0 else []
    source_candidates = database.list_detection_candidates(source_id) if source_width > 0 and source_height > 0 else []
    eligible_relations: list[dict[str, Any]] = []
    for relation in relations:
        if relation["relation_id"] in confirmed_relations:
            continue
        if str(relation.get("status") or "proposed") == "rejected":
            continue
        feedback = feedback_by_relation.get(str(relation["relation_id"]))
        if feedback is None or feedback["hard_reject"]:
            continue
        if int(relation.get("rank") or 1) != 1:
            continue
        value_block = database.get_detected_block(str(relation.get("value_block_id") or ""))
        if value_block is None or source_width <= 0 or source_height <= 0:
            continue
        semantic_box = _block_box(value_block).clamp(source_width, source_height)
        if _pipeline_a_geometry_match(
            database, source_id, semantic_box, source_width, source_height,
            annotations=source_annotations, candidates=source_candidates,
        ) is None:
            continue
        if not str(relation.get("label_text") or ""):
            continue
        eligible_relations.append(relation)

    # The global field profile is authoritative when a label is an exact alias
    # in the correct table context. Without this pass, the later global score
    # sort can assign a same-unit field to the wrong row (for example Stroke
    # Volume -> ED Volume) simply because the labels are spatially duplicated.
    # This mirrors the exact-alias disambiguation in ``suggest_mappings_fast``
    # so that both mapping strategies apply the same safety guard.
    exact_candidates: dict[str, list[tuple[float, dict[str, Any], dict[str, Any]]]] = {}
    for relation in eligible_relations:
        relation_id = str(relation["relation_id"])
        feedback = feedback_by_relation[relation_id]
        for field in fields:
            field_key = str(field["field_key"])
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
            exact_candidates.setdefault(relation_id, []).append((
                score,
                field,
                {
                    **relation,
                    "feedback_quality": float(feedback["quality"]),
                    "feedback_matched_examples": int(feedback["matched_examples"]),
                    "mapping_evidence": evidence,
                },
            ))

    exact_assignments: dict[str, tuple[float, dict[str, Any], dict[str, Any]]] = {}
    exact_field_use: dict[str, int] = {}
    for relation_id, candidates in exact_candidates.items():
        # An exact alias is safe only when the table context leaves one field
        # and that field is not claimed by another exact relation.
        field_keys = {str(item[1]["field_key"]) for item in candidates}
        if len(field_keys) == 1 and len(candidates) == 1:
            exact_assignments[relation_id] = candidates[0]
            field_key = next(iter(field_keys))
            exact_field_use[field_key] = exact_field_use.get(field_key, 0) + 1
    exact_assignments = {
        relation_id: item
        for relation_id, item in exact_assignments.items()
        if exact_field_use.get(str(item[1]["field_key"]), 0) == 1
    }

    suggestions: list[tuple[float, dict[str, Any], dict[str, Any]]] = list(exact_assignments.values())
    for field in fields:
        if field["field_key"] in confirmed_fields:
            continue
        for relation in eligible_relations:
            relation_id = str(relation["relation_id"])
            if relation_id in exact_assignments:
                continue
            if not lateral_candidate_allowed(field, relation, lateral_ambiguities):
                continue
            feedback = feedback_by_relation[relation_id]
            score, evidence = schema_candidate_score(
                field,
                relation,
                similarity=_similarity,
                context_score=_context_score,
                feedback_multiplier=float(feedback["multiplier"]),
            )
            if score >= minimum_score:
                relation_with_feedback = dict(relation)
                relation_with_feedback["feedback_quality"] = float(feedback["quality"])
                relation_with_feedback["feedback_matched_examples"] = int(feedback["matched_examples"])
                relation_with_feedback["mapping_evidence"] = evidence
                suggestions.append((score, field, relation_with_feedback))

    suggestions.sort(key=lambda item: item[0], reverse=True)
    used_fields = set(confirmed_fields)
    used_relations = set(confirmed_relations)
    stored: list[dict[str, Any]] = []
    for score, field, relation in suggestions:
        if field["field_key"] in used_fields or relation["relation_id"] in used_relations:
            continue
        evidence = dict(relation.get("mapping_evidence") or {})
        evidence_notes = []
        if evidence.get("exact_alias"):
            evidence_notes.append("exact_alias")
        if evidence.get("unit_match"):
            evidence_notes.append("unit_match")
        if evidence.get("missing_value"):
            evidence_notes.append("missing_value")
        mapping = database.upsert_mapping(
            source_id=source_id,
            field_key=field["field_key"],
            relation_id=relation["relation_id"],
            label_block_id=str(relation.get("label_block_id") or ""),
            value_block_id=str(relation["value_block_id"]),
            unit_block_id=str(relation.get("unit_block_id") or ""),
            status="suggested",
            mapping_confidence=score,
            notes=(
                "automatic schema suggestion"
                + (f"; evidence={','.join(evidence_notes)}" if evidence_notes else "")
                + (f"; feedback_examples={int(relation.get('feedback_matched_examples') or 0)}"
                   if int(relation.get("feedback_matched_examples") or 0) else "")
            ),
            profile_id=profile_id,
        )
        stored.append(mapping)
        used_fields.add(field["field_key"])
        used_relations.add(relation["relation_id"])
    return stored


def apply_mapping_profile(
    database: TrainingDatabase,
    profile_id: str,
    source_id: str,
    *,
    minimum_score: float = 0.62,
    auto_confirm_score: float = 0.90,
) -> list[dict[str, Any]]:
    profile = database.get_mapping_profile(profile_id)
    if profile is None:
        raise KeyError(profile_id)
    relations = database.list_detected_relations(source_id)
    source = database.get_detection_source(source_id) or {}
    source_width = int(source.get("image_width") or 0)
    source_height = int(source.get("image_height") or 0)
    existing = database.list_mappings(source_id)
    confirmed_fields = {item["field_key"] for item in existing if item["status"] == "confirmed"}
    used_relations = {item["relation_id"] for item in existing if item["status"] == "confirmed" and item["relation_id"]}
    candidates: list[tuple[float, dict[str, Any], dict[str, Any]]] = []
    for rule in profile.get("rules", []):
        field_key = str(rule.get("field_key") or "")
        if not field_key or field_key in confirmed_fields or database.get_field_definition(field_key) is None:
            continue
        expected_label = str(rule.get("label_text") or rule.get("label_normalized") or "")
        expected_context = str(rule.get("context_text") or "")
        for relation in relations:
            if relation["relation_id"] in used_relations:
                continue
            if int(relation.get("rank") or 1) != 1:
                continue
            value_block = database.get_detected_block(str(relation.get("value_block_id") or ""))
            if value_block is None or source_width <= 0 or source_height <= 0:
                continue
            if _pipeline_a_geometry_match(
                database, source_id, _block_box(value_block).clamp(source_width, source_height),
                source_width, source_height,
            ) is None:
                continue
            label_score = _similarity(expected_label, str(relation.get("label_text") or ""))
            context_score = _similarity(expected_context, str(relation.get("context_text") or "")) if expected_context else 0.5
            score = 0.78 * label_score + 0.14 * context_score + 0.08 * float(relation.get("confidence") or 0)
            if score >= minimum_score:
                candidates.append((score, rule, relation))
    candidates.sort(key=lambda item: item[0], reverse=True)
    used_fields = set(confirmed_fields)
    stored: list[dict[str, Any]] = []
    for score, rule, relation in candidates:
        field_key = str(rule["field_key"])
        if field_key in used_fields or relation["relation_id"] in used_relations:
            continue
        auto_confirmed = score >= auto_confirm_score
        stored.append(
            database.upsert_mapping(
                source_id=source_id,
                field_key=field_key,
                relation_id=relation["relation_id"],
                label_block_id=str(relation.get("label_block_id") or ""),
                value_block_id=str(relation["value_block_id"]),
                unit_block_id=str(relation.get("unit_block_id") or ""),
                status="confirmed" if auto_confirmed else "suggested",
                mapping_confidence=score,
                notes=(
                    f"auto-confirmed from mapping profile {profile_id} (score={score:.2f})"
                    if auto_confirmed
                    else f"suggested from mapping profile {profile_id}"
                ),
                profile_id=profile_id,
            )
        )
        used_fields.add(field_key)
        used_relations.add(relation["relation_id"])
    return stored


def auto_confirm_mapping_suggestions(
    database: TrainingDatabase,
    source_id: str,
    *,
    minimum_score: float = 0.90,
) -> list[dict[str, Any]]:
    """Promote only high-confidence, one-to-one suggestions for deployment runs."""
    suggestions = database.list_mappings(source_id, status="suggested")
    existing = database.list_mappings(source_id, status="confirmed")
    confirmed_fields = {str(item.get("field_key") or "") for item in existing}
    confirmed_relations = {
        str(item.get("relation_id") or "") for item in existing
        if str(item.get("relation_id") or "")
    }
    eligible = [
        item for item in suggestions
        if float(item.get("mapping_confidence") or 0) >= float(minimum_score)
        and str(item.get("field_key") or "") not in confirmed_fields
        and str(item.get("relation_id") or "") not in confirmed_relations
    ]
    by_field: dict[str, list[dict[str, Any]]] = {}
    by_relation: dict[str, list[dict[str, Any]]] = {}
    for item in eligible:
        by_field.setdefault(str(item.get("field_key") or ""), []).append(item)
        by_relation.setdefault(str(item.get("relation_id") or ""), []).append(item)
    promoted: list[dict[str, Any]] = []
    for item in eligible:
        field_key = str(item.get("field_key") or "")
        relation_id = str(item.get("relation_id") or "")
        if len(by_field.get(field_key, [])) != 1 or (relation_id and len(by_relation.get(relation_id, [])) != 1):
            continue
        promoted.append(database.upsert_mapping(
            source_id=source_id,
            field_key=field_key,
            relation_id=relation_id,
            label_block_id=str(item.get("label_block_id") or ""),
            value_block_id=str(item.get("value_block_id") or ""),
            unit_block_id=str(item.get("unit_block_id") or ""),
            status="confirmed",
            mapping_confidence=float(item.get("mapping_confidence") or 0),
            notes=(str(item.get("notes") or "") + " auto_confirmed_deployment").strip(),
            profile_id=str(item.get("profile_id") or ""),
        ))
        confirmed_fields.add(field_key)
        if relation_id:
            confirmed_relations.add(relation_id)
    return promoted


def _block_box(block: dict[str, Any]) -> Box:
    return Box(int(block["x1"]), int(block["y1"]), int(block["x2"]), int(block["y2"]))


def _pipeline_a_geometry_match(
    database: TrainingDatabase,
    source_id: str,
    semantic_box: Box,
    image_width: int,
    image_height: int,
    *,
    annotations: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
) -> tuple[Box, dict[str, Any]] | None:
    """Resolve semantic content onto geometry produced by Pipeline A.

    Pipeline B is allowed to recognize and interpret text, but it must not invent
    new crop geometry. Reviewed annotations are authoritative. On new sources, a
    current non-rejected localization candidate is the fallback geometry source.
    """

    def score_box(box: Box) -> tuple[float, float, float]:
        intersection = _intersection_area(semantic_box, box)
        if intersection <= 0:
            return 0.0, 0.0, 0.0
        semantic_coverage = intersection / _area(semantic_box)
        candidate_coverage = intersection / _area(box)
        union = _area(semantic_box) + _area(box) - intersection
        iou = intersection / max(1, union)
        score = 0.58 * semantic_coverage + 0.27 * iou + 0.15 * candidate_coverage
        return score, semantic_coverage, iou

    reviewed_matches: list[tuple[float, Box, dict[str, Any]]] = []
    source_annotations = annotations if annotations is not None else database.list_detection_annotations(source_id, active_only=True)
    for annotation in source_annotations:
        box = Box(
            int(annotation["x1"]), int(annotation["y1"]),
            int(annotation["x2"]), int(annotation["y2"]),
        ).clamp(image_width, image_height)
        score, coverage, iou = score_box(box)
        if coverage >= 0.52 or iou >= 0.30:
            reviewed_matches.append((
                score, box,
                {
                    "geometry_source": "pipeline_a_reviewed_annotation",
                    "annotation_id": str(annotation.get("annotation_id") or ""),
                    "review_status": str(annotation.get("review_status") or annotation.get("provenance") or ""),
                    "pipeline_a_match_score": round(score, 4),
                    "semantic_coverage": round(coverage, 4),
                    "iou": round(iou, 4),
                },
            ))

    if reviewed_matches:
        reviewed_matches.sort(key=lambda item: item[0], reverse=True)
        score, box, diagnostics = reviewed_matches[0]
        diagnostics["semantic_box"] = semantic_box.to_list()
        diagnostics["resolved_box"] = box.to_list()
        return box, diagnostics

    matches: list[tuple[float, int, Box, dict[str, Any]]] = []
    source_candidates = candidates if candidates is not None else database.list_detection_candidates(source_id)
    for candidate in source_candidates:
        if str(candidate.get("review_status") or "") == "rejected":
            continue
        if str(candidate.get("relevance_status") or "") == "irrelevant":
            continue
        if str(candidate.get("status") or "proposed") in {"rejected", "irrelevant"}:
            continue
        box = Box(
            int(candidate["x1"]), int(candidate["y1"]),
            int(candidate["x2"]), int(candidate["y2"]),
        ).clamp(image_width, image_height)
        score, coverage, iou = score_box(box)
        if coverage < 0.62 and iou < 0.38:
            continue
        source_kind = str(candidate.get("source_kind") or "")
        priority = 1 if source_kind == "trained_detector" else 0
        matches.append((
            score, priority, box,
            {
                "geometry_source": f"pipeline_a_candidate:{source_kind or 'fusion'}",
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "candidate_confidence": round(float(candidate.get("confidence") or 0), 4),
                "pipeline_a_match_score": round(score, 4),
                "semantic_coverage": round(coverage, 4),
                "iou": round(iou, 4),
            },
        ))

    if not matches:
        return None
    matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
    score, _priority, box, diagnostics = matches[0]
    diagnostics["semantic_box"] = semantic_box.to_list()
    diagnostics["resolved_box"] = box.to_list()
    return box, diagnostics


def resolve_value_roi_box(
    database: TrainingDatabase,
    value_block_id: str,
    image_width: int,
    image_height: int,
    *,
    padding_pixels: int = 2,
    block: dict[str, Any] | None = None,
    annotations: list[dict[str, Any]] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    table_id: str = "",
    row_index: int = -1,
    column_index: int = -1,
) -> tuple[Box, dict[str, Any]]:
    """Attach Pipeline-B semantics to the confirmed canonical table-cell geometry.

    ``padding_pixels`` is retained for API compatibility but intentionally is not
    applied here: the confirmed table cell is the crop geometry.  The legacy
    Pipeline-A lookup remains only for mappings that predate table geometry.
    """
    del padding_pixels
    block = block if block is not None else database.get_detected_block(value_block_id)
    if block is None:
        raise KeyError(value_block_id)
    if str(block.get("role") or "") != "value":
        raise ValueError(f"Detected block is not a value: {value_block_id}")

    source_id = str(block["source_id"])
    canonical_table_id = str(table_id or block.get("table_id") or "").strip()
    canonical_row = int(row_index if int(row_index) >= 0 else block.get("row_index", -1))
    canonical_column = int(column_index if int(column_index) >= 0 else block.get("column_index", -1))
    if canonical_table_id and canonical_row >= 0 and canonical_column >= 0:
        geometry = database.list_detection_table_geometry(source_id)
        cells = geometry.get("cells") or []
        exact = [
            cell for cell in cells
            if str(cell.get("table_id") or "") == canonical_table_id
            and int(cell.get("row_index", -1)) == canonical_row
            and int(cell.get("column_index", -1)) == canonical_column
        ]
        if not exact:
            # The relation keeps the canonical-GT table id, while the persisted
            # table materialization may have its own stable table id.  Row and
            # value-column are still authoritative; use the value block only to
            # disambiguate repeated tables on the same source.
            semantic_box = _block_box(block).clamp(image_width, image_height)
            same_position = [
                cell for cell in cells
                if int(cell.get("row_index", -1)) == canonical_row
                and int(cell.get("column_index", -1)) == canonical_column
            ]
            def overlap(cell: dict[str, Any]) -> float:
                candidate = Box(int(cell["x1"]), int(cell["y1"]), int(cell["x2"]), int(cell["y2"]))
                ix1, iy1 = max(candidate.x1, semantic_box.x1), max(candidate.y1, semantic_box.y1)
                ix2, iy2 = min(candidate.x2, semantic_box.x2), min(candidate.y2, semantic_box.y2)
                intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                union = candidate.width * candidate.height + semantic_box.width * semantic_box.height - intersection
                return intersection / union if union else 0.0
            exact = sorted(same_position, key=overlap, reverse=True)
        if exact:
            cell = exact[0]
            box = Box(
                int(cell["x1"]), int(cell["y1"]),
                int(cell["x2"]), int(cell["y2"]),
            ).clamp(image_width, image_height)
            return box, {
                "geometry_source": "canonical_table_cell_geometry",
                "table_id": str(cell.get("table_id") or canonical_table_id),
                "row_index": canonical_row,
                "column_index": canonical_column,
                "cell_id": str(cell.get("cell_id") or ""),
                "resolved_box": box.to_list(),
            }

    semantic_box = _block_box(block).clamp(image_width, image_height)
    matched = _pipeline_a_geometry_match(
        database, source_id, semantic_box, image_width, image_height,
        annotations=annotations, candidates=candidates,
    )
    if matched is None:
        raise ValueError(
            "Deze semantische waarde heeft geen overeenkomstige Pipeline-A ROI. "
            "Corrigeer eerst Field Detection / Crop Geometry en voer detectie opnieuw uit."
        )
    return matched


def _crop_hash(crop: Any) -> str:
    import numpy as np
    digest = hashlib.sha256()
    digest.update(str(crop.shape).encode("ascii"))
    digest.update(str(crop.dtype).encode("ascii"))
    digest.update(np.ascontiguousarray(crop).tobytes())
    return digest.hexdigest()


def _joined(tokens: list[Any]) -> tuple[str, float]:
    nonempty = [token for token in tokens if str(getattr(token, "text", "")) != ""]
    if not nonempty:
        return "", 0.0
    text = nonempty[0].text if len(nonempty) == 1 else " ".join(token.text for token in nonempty)
    weights = [max(len(token.text), 1) for token in nonempty]
    confidence = sum(float(token.confidence) * weight for token, weight in zip(nonempty, weights, strict=True)) / sum(weights)
    return text, confidence


def parse_mapped_value(raw_text: str, field: dict[str, Any]) -> dict[str, Any]:
    """Parse generic OCR output according to editable field-schema metadata.

    Explicit dash markers represent a field that is present but has no measured
    value. They are returned as ``parsed_value=None`` with ``parse_status=missing``;
    the original OCR text remains untouched for audit/debugging.
    """
    text = str(raw_text or "")
    data_type = str(field.get("data_type") or "text").strip().lower()
    preferred_unit = str(field.get("preferred_unit") or "").strip()
    result: dict[str, Any] = {
        "raw_text": text,
        "data_type": data_type,
        "parsed_value": None,
        "parsed_unit": preferred_unit,
        "parse_status": "ok",
        "range_valid": None,
    }
    if is_missing_value_text(text):
        result["parse_status"] = "missing"
        return result

    if data_type in {"text", "code", "date", "boolean"}:
        stripped = text.strip()
        if data_type == "boolean":
            normalized = normalize_text(stripped)
            if normalized in {"yes", "ja", "true", "1"}:
                result["parsed_value"] = True
            elif normalized in {"no", "nee", "false", "0"}:
                result["parsed_value"] = False
            else:
                result["parse_status"] = "unparsed"
        else:
            result["parsed_value"] = stripped or None
            if not stripped:
                result["parse_status"] = "empty"
        return result

    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if match is None:
        result["parse_status"] = "unparsed"
        return result
    number = float(match.group(0).replace(",", "."))
    if data_type == "integer":
        if not number.is_integer():
            result["parse_status"] = "non_integer"
        result["parsed_value"] = int(round(number))
    else:
        result["parsed_value"] = number
    trailing = text[match.end():].strip(" \t:;,.()[]")
    if trailing:
        result["parsed_unit"] = trailing
    minimum = field.get("minimum_value")
    maximum = field.get("maximum_value")
    if minimum is not None or maximum is not None:
        result["range_valid"] = (
            (minimum is None or number >= float(minimum))
            and (maximum is None or number <= float(maximum))
        )
    return result


def build_mapping_output_preview(
    relation: dict[str, Any],
    field: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact output shape expected after mapping/value parsing."""
    raw_text = str(relation.get("value_text") or "")
    parsed = parse_mapped_value(raw_text, field)
    field_key = str(field.get("field_key") or "")
    measurement = {
        "display_name": field.get("display_name") or field_key,
        "group": field.get("group_name") or "",
        **parsed,
        "mapping_confidence": round(float(relation.get("confidence") or 0), 4),
        "label_text": relation.get("label_text") or "",
        "source": {
            "relation_type": relation.get("relation_type") or "",
            "table_id": relation.get("table_id") or "",
            "row_index": int(relation.get("row_index", -1)),
            "column_index": int(relation.get("value_column_index", -1)),
        },
    }
    return {"measurements": {field_key: measurement}}


def materialize_confirmed_mappings(
    workspace: str | Path,
    config: AppConfig,
    engine: OCREngine | None = None,
    *,
    source_id: str | None = None,
    padding_pixels: int = 2,
    recognize: bool = False,
    reuse_existing_recognition: bool = False,
) -> dict[str, Any]:
    """Create value ROI samples only after a mapping has been confirmed."""
    import cv2
    import numpy as np

    root = resolve_project_workspace(workspace)
    database = TrainingDatabase(root / "samples.sqlite3")
    mappings = database.list_mappings(source_id, status="confirmed")
    if not mappings:
        raise ValueError("No confirmed mappings are available")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for mapping in mappings:
        grouped.setdefault(str(mapping["source_id"]), []).append(mapping)

    if recognize:
        if engine is None:
            raise ValueError("Recognition was requested without an OCR engine")
        engine.warmup()
    created = 0
    refreshed = 0
    failed = 0
    output_sources: list[str] = []
    current_sample_ids: set[str] = set()
    crop_root = root / "crops" / "original"
    header_root = root / "header_crops"
    output_root = root / "extracted_output"
    crop_root.mkdir(parents=True, exist_ok=True)
    header_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)

    for current_source, source_mappings in grouped.items():
        try:
            source_record = database.get_detection_source(current_source)
            if source_record is None:
                raise ValueError(f"Detection source not found: {current_source}")
            render = root / str(source_record["render_path"])
            image = cv2.imread(str(render), cv2.IMREAD_UNCHANGED)
            if image is None:
                raise FileNotFoundError(f"Source render not found: {render}")
            height, width = image.shape[:2]
            crops: list[np.ndarray] = []
            boxes: list[Box] = []
            geometry_diagnostics: list[dict[str, Any]] = []
            for mapping in source_mappings:
                try:
                    box, geometry = resolve_value_roi_box(
                        database, str(mapping["value_block_id"]), width, height,
                        padding_pixels=padding_pixels,
                        table_id=str(mapping.get("table_id") or ""),
                        row_index=int(mapping.get("row_index", -1)),
                        column_index=int(mapping.get("value_column_index", -1)),
                    )
                except KeyError as exc:
                    raise ValueError(f"Mapped value block no longer exists: {mapping['value_block_id']}") from exc
                crop = image[box.y1:box.y2, box.x1:box.x2]
                if crop.size == 0:
                    raise ValueError(f"Empty mapped crop for {mapping['field_key']}")
                boxes.append(box)
                crops.append(crop)
                geometry_diagnostics.append(geometry)
            if recognize:
                assert engine is not None
                recognized = engine.recognize_many(crops)
                if len(recognized) != len(crops):
                    raise RuntimeError("Recognition result count does not match mapped crop count")
            else:
                recognized = [[] for _ in crops]

            measurements: dict[str, Any] = {}
            source_crop_dir = crop_root / current_source
            source_crop_dir.mkdir(parents=True, exist_ok=True)
            source_header_dir = header_root / current_source
            source_header_dir.mkdir(parents=True, exist_ok=True)
            for mapping, box, crop, tokens, geometry in zip(source_mappings, boxes, crops, recognized, geometry_diagnostics, strict=True):
                field_key = str(mapping["field_key"])
                destination = source_crop_dir / f"{field_key}.png"
                if recognize or not reuse_existing_recognition:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if not cv2.imwrite(str(destination), crop):
                        raise RuntimeError(f"Could not save mapped crop: {destination}")
                if recognize:
                    raw_text, raw_confidence = _joined(tokens)
                    raw_variant = "recognition_only_mapped_generic"
                elif reuse_existing_recognition:
                    raw_text = str(mapping.get("value_text") or "")
                    raw_confidence = float(mapping.get("value_confidence") or 0.0)
                    raw_variant = "existing_recognition_output"
                else:
                    raw_text, raw_confidence = "", 0.0
                    raw_variant = "awaiting_value_recognition"
                label_block = database.get_detected_block(str(mapping.get("label_block_id") or "")) if mapping.get("label_block_id") else None
                header_relative = ""
                header_hash = ""
                label_coords = [-1, -1, -1, -1]
                if recognize and label_block is not None:
                    label_box = Box(int(label_block["x1"]), int(label_block["y1"]), int(label_block["x2"]), int(label_block["y2"])).padded(2).clamp(width, height)
                    header_crop = image[label_box.y1:label_box.y2, label_box.x1:label_box.x2]
                    if header_crop.size:
                        header_path = source_header_dir / f"{field_key}.png"
                        if cv2.imwrite(str(header_path), header_crop):
                            header_relative = header_path.relative_to(root).as_posix()
                            header_hash = _crop_hash(header_crop)
                            label_coords = label_box.to_list()
                sample_id = f"{current_source}_{field_key}"
                current_sample_ids.add(sample_id)
                inserted = database.upsert_sample(
                    {
                        "sample_id": sample_id,
                        "source_id": current_source,
                        "profile": "generic_mapping",
                        "field_key": field_key,
                        "field_label": str(mapping.get("display_name") or field_key),
                        "crop_path": destination.relative_to(root).as_posix() if (recognize or not reuse_existing_recognition) else "",
                        "raw_ocr": raw_text,
                        "raw_confidence": raw_confidence,
                        "raw_variant": raw_variant,
                        "image_width": width,
                        "image_height": height,
                        "roi_x1": box.x1,
                        "roi_y1": box.y1,
                        "roi_x2": box.x2,
                        "roi_y2": box.y2,
                        "extraction_method": "mapped_generic",
                        "locator_confidence": float(mapping.get("mapping_confidence") or 0),
                        "locator_label_text": str(mapping.get("label_text") or ""),
                        "locator_version": MAPPING_ENGINE_VERSION,
                        "locator_label_x1": label_coords[0],
                        "locator_label_y1": label_coords[1],
                        "locator_label_x2": label_coords[2],
                        "locator_label_y2": label_coords[3],
                        "header_crop_path": header_relative,
                        "header_crop_sha256": header_hash,
                        "crop_sha256": _crop_hash(crop) if recognize else hashlib.sha256(
                            f"{current_source}:{box.to_list()}".encode("utf-8")
                        ).hexdigest(),
                    }
                )
                # Mapping reuses the already reviewed Pipeline-A/canonical
                # cell geometry.  This is application-semantic materialization,
                # not a second geometry-review stage.
                database.review_roi(
                    sample_id,
                    "correct",
                    "Bestaande Pipeline-A/canonieke celgeometrie hergebruikt.",
                )
                created += int(inserted)
                refreshed += int(not inserted)
                parsed = parse_mapped_value(raw_text, mapping) if (recognize or reuse_existing_recognition) else {
                    "raw_text": "", "data_type": mapping.get("data_type") or "text",
                    "parsed_value": None,
                    "parsed_unit": mapping.get("preferred_unit") or mapping.get("unit_text") or "",
                    "parse_status": "awaiting_value_recognition", "range_valid": None,
                }
                measurements[field_key] = {
                    "display_name": mapping.get("display_name") or field_key,
                    "group": mapping.get("group_name") or "",
                    **parsed,
                    "confidence": round(raw_confidence, 4),
                    "mapping_confidence": round(float(mapping.get("mapping_confidence") or 0), 4),
                    "mapping_id": mapping.get("mapping_id"),
                    "label_text": mapping.get("label_text") or "",
                    "roi": box.to_list(),
                    "roi_geometry": geometry,
                }
            payload = {
                "schema_version": "2.0",
                "source_id": current_source,
                "mapping_engine": MAPPING_ENGINE_VERSION,
                "generated_at": utc_now(),
                "measurements": measurements,
            }
            (output_root / f"{current_source}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            output_sources.append(current_source)
        except Exception:
            failed += 1
            LOGGER.exception("Could not materialize mapped fields for source %s", current_source)

    # A new table/raster mapping pass is authoritative for the application
    # output.  Older mapped_generic rows belong to an earlier geometry pass and
    # must not remain in the ROI-review queue or be read by the next OCR run.
    # Keep them as historical records, but move them out of the active method.
    stale_samples = 0
    if failed == 0:
        processed_sources = set(output_sources) if source_id is not None else None
        stale_samples = len(
            database.mark_stale_mapped_generic_samples(current_sample_ids, processed_sources)
        )

    manifest = {
        "created_at": utc_now(),
        "mapping_engine": MAPPING_ENGINE_VERSION,
        "source_count": len(grouped),
        "output_sources": output_sources,
        "confirmed_mapping_count": len(mappings),
        "added_samples": created,
        "refreshed_samples": refreshed,
        "failed_sources": failed,
        "active_sample_count": len(current_sample_ids),
        "stale_samples_archived": stale_samples,
        "geometry_authority": "current_confirmed_mapping_from_canonical_table_cells",
        "recognition_deferred": not recognize,
        "recognition_engine": engine.info() if engine is not None and recognize else None,
    }
    (root / "mapping_materialization_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def recognize_approved_mapped_samples(
    workspace: str | Path,
    engine: OCREngine,
    *,
    source_id: str | None = None,
    batch_size: int = 64,
) -> dict[str, Any]:
    """Read only mapped crops whose ROI geometry has been approved."""
    import cv2
    import numpy as np

    root = resolve_project_workspace(workspace)
    database = TrainingDatabase(root / "samples.sqlite3")
    rows = database.list_samples(
        extraction_method="mapped_generic",
        roi_review_status="correct",
        limit=100000,
    )
    if source_id:
        rows = [row for row in rows if str(row.get("source_id")) == source_id]
    if not rows:
        raise ValueError("No approved mapped ROI crops are available for recognition")

    engine.warmup()
    processed = 0
    failed = 0
    outputs: dict[str, dict[str, Any]] = {}
    for start in range(0, len(rows), max(1, int(batch_size))):
        batch_rows = rows[start:start + max(1, int(batch_size))]
        images: list[np.ndarray] = []
        valid_rows: list[dict[str, Any]] = []
        for row in batch_rows:
            path = root / str(row.get("crop_path") or "")
            image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
            if image is None or image.size == 0:
                LOGGER.error("Mapped crop is missing or unreadable: %s", path)
                failed += 1
                continue
            images.append(image)
            valid_rows.append(row)
        if not valid_rows:
            continue
        recognized = engine.recognize_many(images)
        if len(recognized) != len(valid_rows):
            raise RuntimeError("Recognition result count does not match approved mapped crops")
        for row, tokens in zip(valid_rows, recognized, strict=True):
            raw_text, confidence = _joined(tokens)
            database.update_sample_recognition(
                str(row["sample_id"]), raw_text, confidence,
                "recognition_only_mapped_generic",
            )
            mapping_id = hashlib.sha256(
                f"{row['source_id']}|{row['field_key']}".encode("utf-8")
            ).hexdigest()[:32]
            mapping = database.get_mapping(mapping_id) or {}
            source_payload = outputs.setdefault(
                str(row["source_id"]),
                {
                    "schema_version": "2.0",
                    "source_id": row["source_id"],
                    "mapping_engine": MAPPING_ENGINE_VERSION,
                    "recognition_engine": engine.info(),
                    "generated_at": utc_now(),
                    "measurements": {},
                },
            )
            parsed = parse_mapped_value(raw_text, mapping or row)
            source_payload["measurements"][str(row["field_key"])] = {
                "display_name": mapping.get("display_name") or row.get("field_label") or row["field_key"],
                "group": mapping.get("group_name") or "",
                **parsed,
                "confidence": round(float(confidence), 4),
                "mapping_confidence": round(float(mapping.get("mapping_confidence") or row.get("locator_confidence") or 0), 4),
                "mapping_id": mapping.get("mapping_id") or mapping_id,
                "label_text": mapping.get("label_text") or row.get("locator_label_text") or "",
                "roi": [row["roi_x1"], row["roi_y1"], row["roi_x2"], row["roi_y2"]],
            }
            processed += 1

    output_root = root / "extracted_output"
    output_root.mkdir(parents=True, exist_ok=True)
    for current_source, payload in outputs.items():
        (output_root / f"{current_source}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    manifest = {
        "created_at": utc_now(),
        "mapping_engine": MAPPING_ENGINE_VERSION,
        "approved_roi_count": len(rows),
        "recognized_samples": processed,
        "failed_samples": failed,
        "output_sources": sorted(outputs),
        "recognition_engine": engine.info(),
    }
    (root / "mapped_value_recognition_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
