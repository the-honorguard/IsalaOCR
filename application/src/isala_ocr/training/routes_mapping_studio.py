"""Label-first Mapping Studio routes, split out of webui.create_web_app.

Covers /mapping, /mapping-labels (both redirect to the studio),
/mapping/<source_id>/relation-feedback and the studio itself,
/mapping-labels/<source_id>. The older, no-longer-linked-from-nav
ROI-first Mapping Studio (/mapping/<source_id> -> mapping_studio()) is
a separate route, split out on its own into routes_roi_mapping_studio.py.

``database``, ``workspace_root`` and ``enqueue_job`` are reused by
other route groups in webui.py and are passed in explicitly.
Everything else used here (``table_studio_roles``, ``table_studio_rows``,
``load_panel_profile``, ``normalize_text``, ``field_lateral_suffix``,
``field_lateral_side``, ``relation_lateral_side``,
``RELATION_FEEDBACK_REASONS``) is a pure function/constant imported
directly from its own module.

Note: ``label_mapping_studio()`` had a long-standing bug (fixed in a
separate commit just before this extraction) where its second half had
been misplaced as unreachable code inside the ``enforce_primary_workflow_gate``
before_request hook, so it always returned ``None``. That hook itself is
unrelated to this route group and stays in webui.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from .generic_detection import normalize_text
from .mapping_lateral import field_lateral_side, field_lateral_suffix, relation_lateral_side
from .relation_feedback import RELATION_FEEDBACK_REASONS
from .recognition_ground_truth import table_studio_roles, table_studio_rows
from .table_panels import load_panel_profile


def register_mapping_studio_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    enqueue_job: Callable[..., dict[str, Any]],
) -> None:
    def _first_open_mapping_source(sources: list[dict[str, Any]]) -> str | None:
        """Return the first source that still needs Mapping Studio review.

        list_detected_relations() already LEFT JOINs field_mappings and
        exposes the result as mapping_status, so this only needs the one
        query per source instead of also calling list_mappings(source_id)
        just to look the same status back up by relation_id.
        """
        for item in sources:
            source_id = str(item.get("source_id") or "")
            if not source_id:
                continue
            relations = [
                relation for relation in database.list_detected_relations(source_id)
                if str(relation.get("relation_type") or "") == "table_cell"
                and str(relation.get("label_text") or "").strip()
            ]
            if not relations:
                continue
            if any(str(relation.get("mapping_status") or "") != "confirmed" for relation in relations):
                return source_id
        return None

    @app.get("/mapping")
    def mapping_index():
        sources = database.list_detection_sources()
        if not sources:
            return render_template("mapping_empty.html")
        requested = str(request.args.get("source_id") or "").strip()
        valid_source_ids = {str(item["source_id"]) for item in sources}
        if requested in valid_source_ids:
            source_id = requested
        else:
            source_id = _first_open_mapping_source(sources) or str(sources[0]["source_id"])
        return redirect(url_for("label_mapping_studio", source_id=source_id))

    @app.get("/mapping-labels")
    def label_mapping_index():
        sources = database.list_detection_sources()
        if not sources:
            return render_template("mapping_empty.html")
        requested = str(request.args.get("source_id") or "").strip()
        valid_source_ids = {str(item["source_id"]) for item in sources}
        if requested in valid_source_ids:
            source_id = requested
        else:
            source_id = _first_open_mapping_source(sources) or str(sources[0]["source_id"])
        return redirect(url_for("label_mapping_studio", source_id=source_id))

    @app.post("/mapping/<source_id>/relation-feedback")
    def mapping_relation_feedback(source_id: str):
        if database.get_detection_source(source_id) is None:
            abort(404)
        payload = request.get_json(silent=True) or request.form
        relation_id = str(payload.get("relation_id") or "").strip()
        feedback_action = str(payload.get("action") or "reject").strip().lower()
        if not relation_id:
            return jsonify({"ok": False, "error": "relation_id ontbreekt"}), 400
        try:
            if feedback_action == "restore":
                database.clear_relation_feedback(source_id, relation_id)
                result = {
                    "ok": True,
                    "status": "proposed",
                    "reason_code": "",
                    "reason_label": "",
                    "reason_detail": "",
                }
            elif feedback_action == "reject":
                reason_code = str(payload.get("reason_code") or "").strip().lower()
                reason_detail = str(payload.get("reason_detail") or "").strip()
                feedback = database.record_relation_feedback(
                    source_id=source_id,
                    relation_id=relation_id,
                    verdict="rejected",
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                )
                result = {
                    "ok": True,
                    "status": "rejected",
                    "reason_code": feedback["reason_code"],
                    "reason_label": RELATION_FEEDBACK_REASONS.get(feedback["reason_code"], feedback["reason_code"]),
                    "reason_detail": feedback["reason_detail"],
                }
            else:
                return jsonify({"ok": False, "error": "Onbekende feedbackactie"}), 400
        except (KeyError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        result["stats"] = database.relation_feedback_stats()
        return jsonify(result)

    @app.route("/mapping-labels/<source_id>", methods=["GET", "POST"])
    def label_mapping_studio(source_id: str):
        """Label-first Mapping Studio, independent of ROI review."""
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        fields = database.list_field_definitions(active_only=True)
        all_relations = [
            item for item in database.list_detected_relations(source_id)
            if str(item.get("relation_type") or "") == "table_cell"
            and str(item.get("label_text") or "").strip()
        ]
        column_roles = table_studio_roles(workspace_root())
        active_rows = table_studio_rows(workspace_root())
        panel_profile = load_panel_profile(workspace_root())
        panel_by_id = {
            str(panel.get("panel_id") or ""): panel
            for panel in panel_profile.get("panels") or []
            if str(panel.get("panel_id") or "")
        }
        geometry = database.list_detection_table_geometry(source_id)
        image_width = float(source.get("image_width") or panel_profile.get("reference_width") or 0)
        image_height = float(source.get("image_height") or panel_profile.get("reference_height") or 0)
        raw_table_panels: dict[str, str] = {}
        for region in geometry.get("regions", []):
            center_x = (float(region.get("x1") or 0) + float(region.get("x2") or 0)) / 2
            center_y = (float(region.get("y1") or 0) + float(region.get("y2") or 0)) / 2
            for panel_id, panel in panel_by_id.items():
                if (
                    float(panel.get("x1") or 0) * image_width <= center_x <= float(panel.get("x2") or 0) * image_width
                    and float(panel.get("y1") or 0) * image_height <= center_y <= float(panel.get("y2") or 0) * image_height
                ):
                    raw_table_panels[str(region.get("table_id") or "")] = panel_id
                    break
        raster_rows: dict[str, dict[int, tuple[int, int]]] = {}
        for cell in geometry.get("cells", []):
            panel_id = raw_table_panels.get(str(cell.get("table_id") or ""), "")
            if not panel_id:
                continue
            row_index = int(cell.get("row_index") or 0)
            y1, y2 = int(cell.get("y1") or 0), int(cell.get("y2") or 0)
            previous = raster_rows.setdefault(panel_id, {}).get(row_index)
            raster_rows[panel_id][row_index] = (
                min(y1, previous[0]) if previous else y1,
                max(y2, previous[1]) if previous else y2,
            )

        def relation_panel_id(relation: dict[str, Any]) -> str:
            parts = [part.strip() for part in str(relation.get("context_text") or "").split("|")]
            # Panel context is persisted as human-readable name plus optional
            # id. Older mapping runs only persisted the name, so do not assume
            # that the id is always the second token. The selected Table/Panel
            # remains the semantic disambiguator for generic labels such as
            # ``ED Volume``; no report-specific label is hardcoded here.
            normalized_parts = {normalize_text(part) for part in parts if part}
            for panel_id, panel in panel_by_id.items():
                panel_name = normalize_text(str(panel.get("name") or ""))
                if normalize_text(panel_id) in normalized_parts or (
                    panel_name and panel_name in normalized_parts
                ):
                    return panel_id
            return ""

        def relation_raster_row(relation: dict[str, Any], panel_id: str) -> int:
            rows = raster_rows.get(panel_id) or {}
            if not rows:
                return int(relation.get("row_index") or -1)
            center_y = (int(relation.get("label_y1") or 0) + int(relation.get("label_y2") or 0)) / 2
            containing = [index for index, (y1, y2) in rows.items() if y1 <= center_y <= y2]
            if containing:
                return containing[0]
            return min(rows, key=lambda index: abs(((rows[index][0] + rows[index][1]) / 2) - center_y))

        relations = []
        for relation in all_relations:
            panel_id = relation_panel_id(relation)
            value_column = str(int(relation.get("value_column_index") or 0))
            raster_row = relation_raster_row(relation, panel_id)
            configured = panel_id in column_roles
            if configured and column_roles.get(panel_id, {}).get(value_column) != "value":
                continue
            if panel_id in active_rows and raster_row not in set(active_rows[panel_id]):
                continue
            panel = panel_by_id.get(panel_id) or {}
            relations.append({
                **relation,
                "panel_id": panel_id,
                "panel_name": str(panel.get("name") or panel_id or "Tabel"),
                "raster_row_index": raster_row,
                "table_configured": configured,
            })
        relations.sort(key=lambda item: (
            str(item.get("panel_name") or ""),
            int(item.get("raster_row_index") or -1),
            int(item.get("value_column_index") or -1),
            str(item.get("label_text") or "").casefold(),
        ))
        relations_by_id = {str(item["relation_id"]): item for item in relations}

        def generic_field_options() -> list[dict[str, Any]]:
            options: list[dict[str, Any]] = []
            seen: set[str] = set()
            for field in fields:
                family = field_lateral_suffix(field) or str(field.get("field_key") or "")
                if not family or family in seen:
                    continue
                seen.add(family)
                display_name = str(field.get("display_name") or family)
                group_name = str(field.get("group_name") or "")
                prefix = f"{group_name} "
                if prefix and display_name.casefold().startswith(prefix.casefold()):
                    display_name = display_name[len(prefix):]
                options.append({"family": family, "display_name": display_name})
            return options

        field_options = generic_field_options()

        if request.method == "POST":
            action = str(request.form.get("label_mapping_action") or "save").strip().lower()
            if action == "rebuild":
                job = enqueue_job("20")
                flash("Mappingvoorstellen opnieuw opgebouwd; controleer de nieuwe voorstellen zodra de taak gereed is.", "success")
                return redirect(url_for("label_mapping_studio", source_id=source_id, job_id=job["job_id"]))
            if action != "save":
                abort(400)
            assignments = [
                {
                    "relation_id": relation_id,
                    "field_key": str(request.form.get(f"field_{relation_id}") or "").strip(),
                    "notes": "label-first mapping",
                }
                for relation_id in request.form.getlist("relation_id")
                if relation_id in relations_by_id
            ]
            resolution_error = ""
            for assignment in assignments:
                selected = assignment["field_key"]
                if not selected.startswith("family:"):
                    continue
                family = selected.removeprefix("family:")
                relation = relations_by_id[assignment["relation_id"]]
                side = relation_lateral_side(relation)
                candidates = [
                    field for field in fields
                    if (field_lateral_suffix(field) or str(field.get("field_key") or "")) == family
                    and (not side or not field_lateral_side(field) or field_lateral_side(field) == side)
                ]
                if len(candidates) != 1:
                    resolution_error = f"Kan algemene veldnaam '{family}' niet eenduidig koppelen aan de gekozen tabel/panel."
                    break
                assignment["field_key"] = str(candidates[0]["field_key"])
            if resolution_error:
                flash(f"Labelmappings niet opgeslagen: {resolution_error}", "error")
                return redirect(url_for("label_mapping_studio", source_id=source_id))
            try:
                result = database.sync_relation_mappings(source_id, assignments)
            except (KeyError, ValueError) as exc:
                flash(f"Labelmappings niet opgeslagen: {exc}", "error")
            else:
                flash(
                    f"{result['saved']} labelmapping(s) opgeslagen, {result['removed']} verwijderd.",
                    "success",
                )
            return redirect(url_for("label_mapping_studio", source_id=source_id))

        mappings = database.list_mappings(source_id)
        mappings_by_relation = {
            str(item["relation_id"]): item
            for item in mappings
            if str(item.get("relation_id") or "")
        }
        relation_groups: list[dict[str, Any]] = []
        for relation in relations:
            panel_id = str(relation.get("panel_id") or relation.get("table_id") or "")
            if not relation_groups or relation_groups[-1]["panel_id"] != panel_id:
                relation_groups.append({
                    "panel_id": panel_id,
                    "panel_name": str(relation.get("panel_name") or "Tabel"),
                    "relations": [],
                })
            relation_groups[-1]["relations"].append(relation)
        return render_template(
            "mapping_labels_studio.html",
            source=source,
            source_id=source_id,
            sources=database.list_detection_sources(),
            relations=relations,
            relation_groups=relation_groups,
            mappings_by_relation=mappings_by_relation,
            fields=fields,
            field_options=field_options,
            table_roles_configured=bool(column_roles),
            header_counts={
                "total": len(relations),
                "pending": sum(
                    1 for relation in relations
                    if str(mappings_by_relation.get(str(relation["relation_id"]), {}).get("status") or "") != "confirmed"
                ),
                "accepted": sum(
                    1 for relation in relations
                    if str(mappings_by_relation.get(str(relation["relation_id"]), {}).get("status") or "") == "confirmed"
                ),
            },
            header_total_label="labels",
            header_pending_label="te koppelen",
            header_accepted_label="gekoppeld",
        )
