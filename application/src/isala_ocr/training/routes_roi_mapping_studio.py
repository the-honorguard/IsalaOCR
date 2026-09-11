"""ROI-first Mapping Studio route, split out of webui.create_web_app.

Covers the older, no-longer-linked-from-nav /mapping/<source_id> route
(``mapping_studio()``), as flagged as a later pass in
``routes_mapping_studio.py``'s docstring (the current, label-first Mapping
Studio lives there). ``database`` and ``enqueue_job`` are still shared with
other route groups defined directly in webui.py, so they are passed in
explicitly; everything else used here (``resolve_value_roi_box``,
``suggest_mappings``, ``build_mapping_output_preview``,
``RELATION_FEEDBACK_REASONS``) is a pure function/constant imported
directly from its own module.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from .mapping import build_mapping_output_preview, resolve_value_roi_box, suggest_mappings
from .relation_feedback import RELATION_FEEDBACK_REASONS


def register_roi_mapping_studio_routes(app: Flask, *, database: Any, enqueue_job: Any) -> None:
    @app.route("/mapping/<source_id>", methods=["GET", "POST"])
    def mapping_studio(source_id: str):
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        relations = database.list_detected_relations(source_id)
        relations_by_id = {str(item["relation_id"]): item for item in relations}
        fields = database.list_field_definitions(active_only=True)
        pipeline_a_annotations: list[dict[str, Any]] | None = None
        pipeline_a_candidates: list[dict[str, Any]] | None = None
        value_blocks_cache: dict[str, dict[str, Any]] | None = None

        def resolve_mapping_roi(value_block_id: str) -> tuple[Any, dict[str, Any]]:
            nonlocal pipeline_a_annotations, pipeline_a_candidates, value_blocks_cache
            if pipeline_a_annotations is None:
                pipeline_a_annotations = database.list_detection_annotations(source_id, active_only=True)
                pipeline_a_candidates = database.list_detection_candidates(source_id)
                if value_blocks_cache is None:
                    value_blocks_cache = {
                        str(item["block_id"]): item
                        for item in database.list_detected_blocks(source_id, role="value", semantic_only=True)
                    }
            block = (value_blocks_cache or {}).get(str(value_block_id))
            return resolve_value_roi_box(
                database, str(value_block_id), int(source["image_width"]), int(source["image_height"]),
                block=block, annotations=pipeline_a_annotations, candidates=pipeline_a_candidates,
            )
        if request.method == "POST":
            action = str(request.form.get("mapping_action") or "save").strip().lower()
            saved = 0
            if action in {"save", "save_apply"}:
                posted_relation_ids = [
                    str(value) for value in request.form.getlist("relation_id")
                    if str(value) in relations_by_id
                ]
                desired = {
                    relation_id: str(request.form.get(f"field_{relation_id}") or "").strip()
                    for relation_id in posted_relation_ids
                }
                selected_fields = [field_key for field_key in desired.values() if field_key]
                duplicate_fields = sorted({
                    field_key for field_key in selected_fields
                    if selected_fields.count(field_key) > 1
                })
                if duplicate_fields:
                    names = {str(item["field_key"]): str(item.get("display_name") or item["field_key"]) for item in fields}
                    labels = ", ".join(names.get(key, key) for key in duplicate_fields)
                    flash(
                        f"Niet opgeslagen: hetzelfde functionele veld is meerdere keren geselecteerd ({labels}).",
                        "error",
                    )
                    return redirect(url_for("mapping_studio", source_id=source_id))

                assignments = [
                    {
                        "relation_id": relation_id,
                        "field_key": field_key,
                        "notes": str(request.form.get(f"notes_{relation_id}") or ""),
                    }
                    for relation_id, field_key in desired.items()
                ]
                try:
                    for assignment in assignments:
                        if not assignment["field_key"]:
                            continue
                        relation = relations_by_id[assignment["relation_id"]]
                        resolve_mapping_roi(str(relation["value_block_id"]))
                    sync_result = database.sync_relation_mappings(source_id, assignments)
                except (KeyError, ValueError) as exc:
                    flash(f"Mappings niet opgeslagen: {exc}", "error")
                    return redirect(url_for("mapping_studio", source_id=source_id))
                saved = int(sync_result["saved"])
                removed = int(sync_result["removed"])
                changed = saved + removed
                if changed:
                    flash(
                        f"{saved} mapping(s) opgeslagen, {removed} verwijderd. Gewijzigde ROI's zijn gemarkeerd als verouderd tot 'Mapping toepassen' opnieuw is uitgevoerd.",
                        "success",
                    )
                else:
                    flash("Geen mappingwijzigingen om op te slaan.", "success")
                if action == "save_apply":
                    job = enqueue_job("21", {"source_id": source_id})
                    return redirect(url_for("mapping_studio", source_id=source_id, job_id=job["job_id"]))
            elif action == "confirm_suggestions":
                selected = set(request.form.getlist("mapping_id"))
                candidates = database.list_mappings(source_id, status="suggested")
                for item in candidates:
                    if str(item["mapping_id"]) not in selected:
                        continue
                    try:
                        resolve_mapping_roi(str(item["value_block_id"]))
                    except (KeyError, ValueError):
                        continue
                    database.upsert_mapping(
                        source_id=source_id,
                        field_key=str(item["field_key"]),
                        relation_id=str(item.get("relation_id") or ""),
                        label_block_id=str(item.get("label_block_id") or ""),
                        value_block_id=str(item["value_block_id"]),
                        unit_block_id=str(item.get("unit_block_id") or ""),
                        status="confirmed",
                        mapping_confidence=float(item.get("mapping_confidence") or 0),
                        notes=str(item.get("notes") or "") + " confirmed_by_user",
                        profile_id=str(item.get("profile_id") or ""),
                    )
                    saved += 1
                flash(f"{saved} voorgestelde mapping(s) bevestigd.", "success")
            elif action == "suggest":
                suggestions = suggest_mappings(database, source_id)
                flash(f"{len(suggestions)} nieuwe mappings voorgesteld op basis van aliassen en context.", "success")
            elif action == "regenerate":
                job = enqueue_job("20")
                flash("De vorige Mapping-dataset wordt gewist en opnieuw opgebouwd met de actuele tabelstructuur en OCR.", "success")
                return redirect(url_for("mapping_studio", source_id=source_id, job_id=job["job_id"]))
            elif action == "custom":
                field_key = str(request.form.get("custom_field_key") or "").strip()
                label_block_id = str(request.form.get("custom_label_block_id") or "").strip()
                value_block_id = str(request.form.get("custom_value_block_id") or "").strip()
                if not field_key or not value_block_id:
                    flash("Kies minimaal een functioneel veld en een waardeblok.", "error")
                else:
                    try:
                        resolve_mapping_roi(value_block_id)
                    except (KeyError, ValueError) as exc:
                        flash(f"Kan niet mappen zonder geldige Pipeline-A ROI: {exc}", "error")
                        return redirect(url_for("mapping_studio", source_id=source_id))
                    database.upsert_mapping(
                        source_id=source_id,
                        field_key=field_key,
                        relation_id="",
                        label_block_id=label_block_id,
                        value_block_id=value_block_id,
                        status="confirmed",
                        mapping_confidence=1.0,
                        notes="manual block mapping",
                    )
                    flash("Handmatige mapping opgeslagen.", "success")
            elif action == "delete":
                mapping_id = str(request.form.get("mapping_id_single") or "").strip()
                if mapping_id:
                    database.delete_mapping(mapping_id)
                    flash("Mapping verwijderd.", "success")
            else:
                abort(400)
            return redirect(url_for("mapping_studio", source_id=source_id))

        mappings = database.list_mappings(source_id)
        mappings_by_relation = {
            str(item["relation_id"]): item for item in mappings if str(item.get("relation_id") or "")
        }
        confirmed_fields = {str(item["field_key"]) for item in mappings if item["status"] == "confirmed"}
        label_blocks = database.list_detected_blocks(source_id, role="label", semantic_only=True)
        value_blocks = database.list_detected_blocks(source_id, role="value", semantic_only=True)
        value_blocks_cache = {str(item["block_id"]): item for item in value_blocks}
        fields_by_key = {str(item["field_key"]): item for item in fields}
        feedback_by_relation = database.feedback_for_relations(source_id, relations)
        feedback_stats = database.relation_feedback_stats()
        for relation in relations:
            try:
                roi_box, roi_diag = resolve_mapping_roi(str(relation["value_block_id"]))
                relation["pipeline_a_roi_ready"] = True
                relation["pipeline_a_roi"] = roi_box.to_list()
                relation["pipeline_a_geometry_source"] = str(roi_diag.get("geometry_source") or "")
                relation["pipeline_a_match_score"] = float(roi_diag.get("pipeline_a_match_score") or 0)
            except (KeyError, ValueError):
                relation["pipeline_a_roi_ready"] = False
                relation["pipeline_a_roi"] = []
                relation["pipeline_a_geometry_source"] = ""
                relation["pipeline_a_match_score"] = 0.0
        # Pipeline B receives only relations backed by relevant, reviewed
        # Pipeline-A geometry. Out-of-scope/ignored regions are intentionally
        # absent from Mapping Studio instead of appearing as disabled noise.
        hidden_relation_count = sum(1 for relation in relations if not relation.get("pipeline_a_roi_ready"))
        relations = [relation for relation in relations if relation.get("pipeline_a_roi_ready")]
        allowed_value_block_ids = {str(relation.get("value_block_id") or "") for relation in relations}
        value_blocks = [block for block in value_blocks if str(block.get("block_id") or "") in allowed_value_block_ids]
        visible_relation_ids = {str(relation.get("relation_id") or "") for relation in relations}
        mappings = [
            item for item in mappings
            if not str(item.get("relation_id") or "") or str(item.get("relation_id") or "") in visible_relation_ids
        ]
        mappings_by_relation = {
            str(item["relation_id"]): item for item in mappings if str(item.get("relation_id") or "")
        }
        confirmed_fields = {str(item["field_key"]) for item in mappings if item["status"] == "confirmed"}
        preview_relations = {
            str(item["relation_id"]): {
                "relation_id": str(item["relation_id"]),
                "label_text": str(item.get("label_text") or ""),
                "value_text": str(item.get("value_text") or ""),
                "confidence": float(item.get("confidence") or 0),
                "relation_type": str(item.get("relation_type") or ""),
                "table_id": str(item.get("table_id") or ""),
                "row_index": int(item.get("row_index", -1)),
                "value_column_index": int(item.get("value_column_index", -1)),
                "label_x1": int(item.get("label_x1") or 0),
                "label_y1": int(item.get("label_y1") or 0),
                "label_x2": int(item.get("label_x2") or 0),
                "label_y2": int(item.get("label_y2") or 0),
                "value_x1": int(item.get("value_x1") or 0),
                "value_y1": int(item.get("value_y1") or 0),
                "value_x2": int(item.get("value_x2") or 0),
                "value_y2": int(item.get("value_y2") or 0),
                "pipeline_a_roi_ready": bool(item.get("pipeline_a_roi_ready")),
                "pipeline_a_roi": item.get("pipeline_a_roi") or [],
                "pipeline_a_geometry_source": str(item.get("pipeline_a_geometry_source") or ""),
                "pipeline_a_match_score": float(item.get("pipeline_a_match_score") or 0),
            }
            for item in relations
        }
        preview_fields = {
            key: {
                "field_key": key,
                "display_name": item.get("display_name") or key,
                "group_name": item.get("group_name") or "",
                "data_type": item.get("data_type") or "text",
                "preferred_unit": item.get("preferred_unit") or "",
                "minimum_value": item.get("minimum_value"),
                "maximum_value": item.get("maximum_value"),
            }
            for key, item in fields_by_key.items()
        }
        initial_preview = None
        for relation in relations:
            current = mappings_by_relation.get(str(relation["relation_id"]))
            if current and str(current.get("field_key") or "") in fields_by_key:
                initial_preview = build_mapping_output_preview(relation, fields_by_key[str(current["field_key"])])
                break
        return render_template(
            "mapping_studio.html",
            source=source,
            source_id=source_id,
            sources=database.list_detection_sources(),
            relations=relations,
            mappings=mappings,
            mappings_by_relation=mappings_by_relation,
            confirmed_fields=confirmed_fields,
            fields=fields,
            label_blocks=label_blocks,
            value_blocks=value_blocks,
            preview_relations=preview_relations,
            preview_fields=preview_fields,
            initial_preview=initial_preview,
            feedback_by_relation=feedback_by_relation,
            feedback_stats=feedback_stats,
            feedback_reasons=RELATION_FEEDBACK_REASONS,
            hidden_relation_count=hidden_relation_count,
            header_counts={"total": len(relations), "pending": sum(item["status"] == "suggested" for item in mappings), "accepted": sum(item["status"] == "confirmed" for item in mappings)},
            header_total_label="relaties", header_pending_label="voorgesteld", header_accepted_label="bevestigd",
        )
