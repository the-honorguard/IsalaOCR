"""Label-first Mapping Studio routes, split out of webui.create_web_app.

Covers /mapping, /mapping-labels (both redirect to the studio),
/mapping/<source_id>/relation-feedback and the studio itself,
/mapping-labels/<source_id>. The older, no-longer-linked-from-nav
ROI-first Mapping Studio (/mapping/<source_id> -> mapping_studio()) is
a separate route, split out on its own into routes_roi_mapping_studio.py.

``database``, ``workspace_root`` and ``enqueue_job`` are reused by
other route groups in webui.py and are passed in explicitly.
Everything else used here (``table_studio_roles``, ``table_studio_rows``,
``relation_panel_id``, ``load_panel_profile``, ``field_lateral_suffix``,
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

import cv2
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from .json_api import json_error
from .label_history import label_family_history, suggest_family_for_label
from .mapping_lateral import field_lateral_side, field_lateral_suffix, relation_lateral_side
from .relation_feedback import RELATION_FEEDBACK_REASONS
from .recognition_ground_truth import (
    relation_column_eligible, relation_panel_id, save_unrecognized_panel_policy,
    table_studio_roles, table_studio_rows, unrecognized_panel_policy,
)
from .table_cell_ground_truth import list_ground_truth_sources
from .table_panels import load_panel_profile
from .table_semantics import load_assignments as load_table_semantic_assignments
from .test_pipeline_sources import test_pipeline_source_ids


def _table_crop_box(
    relations: list[dict[str, Any]], image_width: int, image_height: int, *, padding: int = 24,
) -> tuple[int, int, int, int] | None:
    """The bounding box (x1, y1, x2, y2) covering every label/value box of
    ``relations`` (expected: one table's relations), padded and clamped to
    the image. ``None`` when none of them carry usable geometry.

    Shared, pixel-for-pixel, by the review queue's image-overlay percentages
    and by the route that crops and serves that same image, so a box drawn
    at "12% from the left" in the template is guaranteed to land on the same
    pixel the crop route actually cut there.
    """
    xs1: list[int] = []
    ys1: list[int] = []
    xs2: list[int] = []
    ys2: list[int] = []
    for relation in relations:
        for prefix in ("label", "value"):
            x1, y1 = relation.get(f"{prefix}_x1"), relation.get(f"{prefix}_y1")
            x2, y2 = relation.get(f"{prefix}_x2"), relation.get(f"{prefix}_y2")
            if x1 is None or y1 is None or x2 is None or y2 is None:
                continue
            xs1.append(int(x1)); ys1.append(int(y1))
            xs2.append(int(x2)); ys2.append(int(y2))
    if not xs1:
        return None
    x1 = max(0, min(xs1) - padding)
    y1 = max(0, min(ys1) - padding)
    x2 = min(int(image_width), max(xs2) + padding)
    y2 = min(int(image_height), max(ys2) + padding)
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _overlay_box_style(
    box: tuple[int, int, int, int] | None, crop: tuple[int, int, int, int],
) -> dict[str, float] | None:
    """``box`` positioned as a percentage of ``crop``, for an absolutely
    positioned overlay ``<span>`` over the crop image."""
    if box is None:
        return None
    crop_x1, crop_y1, crop_x2, crop_y2 = crop
    crop_width, crop_height = crop_x2 - crop_x1, crop_y2 - crop_y1
    if crop_width <= 0 or crop_height <= 0:
        return None
    x1, y1, x2, y2 = box
    return {
        "left": (x1 - crop_x1) / crop_width * 100,
        "top": (y1 - crop_y1) / crop_height * 100,
        "width": (x2 - x1) / crop_width * 100,
        "height": (y2 - y1) / crop_height * 100,
    }


def register_mapping_studio_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    enqueue_job: Callable[..., dict[str, Any]],
    safe_workspace_file: Callable[[str | Path], Path],
    cached_render_image: Callable[[Path], Any],
    canonical_table_gt_mode: Callable[[], bool] = lambda: False,
) -> None:
    def _training_pipeline_sources() -> list[dict[str, Any]]:
        """The sources an operator is actually expected to work through in
        Mapping Studio, in canonical-GT (table_first) mode: only the ones
        promoted to canonical Ground Truth in Stap 5's GT Studio, excluding
        disposable proefpagina test runs.

        ``detection_sources`` accumulates a row for *every* image the
        detector ever ran on automatically, long before an operator reviews
        or approves anything - and separately, every proefpagina
        ('/test-pipeline') rerun permanently adds its own row indistinguishable
        from a real training-pipeline source (see ``test_pipeline_sources.py``'s
        module docstring). Without both filters, Mapping Studio's "Bron" list
        and review queue included both kinds of noise: on this project, 153
        raw rows for roughly 30 sources an operator had actually curated
        through GT Studio.

        Every other training-review page already excludes proefpagina reruns
        via ``test_pipeline_source_ids()``
        (``webui.py``/``routes_documents.py``); the canonical-GT restriction
        mirrors ``routes_detection_review.py``'s own use of
        ``list_ground_truth_sources()`` to scope its "GT Studio" listing the
        same way. A project not in canonical-GT mode has no such curated
        subset to restrict to, so it keeps seeing every non-test source, as
        before.
        """
        excluded = test_pipeline_source_ids(workspace_root())
        sources = [
            item for item in database.list_detection_sources()
            if str(item.get("source_id") or "") not in excluded
        ]
        if canonical_table_gt_mode():
            canonical_ids = {
                str(item.get("source_id") or "")
                for item in list_ground_truth_sources(workspace_root())
            }
            sources = [item for item in sources if str(item.get("source_id") or "") in canonical_ids]
        return sources

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
        sources = _training_pipeline_sources()
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
        sources = _training_pipeline_sources()
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
            return json_error("relation_id ontbreekt", 400)
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
                return json_error("Onbekende feedbackactie", 400)
        except (KeyError, ValueError) as exc:
            return json_error(str(exc), 400)
        result["stats"] = database.relation_feedback_stats()
        return jsonify(result)

    @app.get("/mapping-labels/<source_id>/table-image/<table_id>")
    def label_mapping_table_image(source_id: str, table_id: str):
        """The source render cropped to one table's labels+values, for the
        review queue's image overlay (see ``_table_crop_box()``)."""
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        relations = [
            item for item in database.list_detected_relations(source_id)
            if str(item.get("relation_type") or "") == "table_cell"
            and str(item.get("table_id") or "") == table_id
        ]
        crop = _table_crop_box(relations, int(source.get("image_width") or 0), int(source.get("image_height") or 0))
        if crop is None:
            abort(404)
        render = safe_workspace_file(str(source.get("render_path") or ""))
        if not render.is_file():
            abort(404)
        image = cached_render_image(render)
        if image is None:
            abort(404)
        x1, y1, x2, y2 = crop
        cropped = image[y1:y2, x1:x2]
        if cropped.size == 0:
            abort(404)
        ok, encoded = cv2.imencode(".png", cropped)
        if not ok:
            abort(500)
        return Response(encoded.tobytes(), mimetype="image/png", headers={"Cache-Control": "no-store"})

    def _load_label_mapping_context(source_id: str) -> dict[str, Any]:
        """Build everything both the bulk Mapping Studio page and the
        one-at-a-time review queue need: the eligible, ordered relations
        (each annotated with panel/table/row context and, when unmapped, an
        ``auto_suggested_family``/``auto_suggested_count`` per
        ``label_history.py``), the generic field dropdown options, and the
        current mappings by relation. Split out so the queue view does not
        have to re-derive raster rows, panel names and history suggestions
        with its own copy of this logic.
        """
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
        panel_policy = unrecognized_panel_policy(workspace_root())
        panel_profile = load_panel_profile(workspace_root())
        # Stap 6 ("Tabelregio selecteren") is where an operator explicitly
        # assigns each table region a semantic name (typically left/right).
        # That name is the authoritative left/right signal - the Panel
        # config from Stap 1 is a separate, purely geometric feature and its
        # panel_name is often generic ("Panel 1"). Without this, ambiguous
        # bilateral fields (e.g. Ejectiefractie for LV and RV) can never be
        # told apart by relation_lateral_side() even though the operator
        # already resolved that ambiguity in Stap 6.
        table_semantic_names = load_table_semantic_assignments(workspace_root())
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
            panel_id = relation_panel_id(relation, panel_by_id)
            raster_row = relation_raster_row(relation, panel_id)
            configured = panel_id in column_roles
            # Display eligibility deliberately never hides an unrecognized-
            # panel relation (unlike the automatic suggesters in mapping.py /
            # mapping_fast.py, which do apply panel_policy here): an operator
            # reviewing this list needs to *see* the row to notice Panel Setup
            # is wrong for it at all. "block" instead disables saving it
            # below (``blocked_unrecognized_panel``), which keeps the row
            # visible rather than making it vanish without explanation.
            if not relation_column_eligible(relation, panel_by_id=panel_by_id, column_roles=column_roles):
                continue
            if panel_id in active_rows and raster_row not in set(active_rows[panel_id]):
                continue
            panel = panel_by_id.get(panel_id) or {}
            semantic_name = str(
                table_semantic_names.get(str(relation.get("table_id") or ""), {}).get("table_name") or ""
            )
            relations.append({
                **relation,
                "panel_id": panel_id,
                "panel_name": str(panel.get("name") or panel_id or "Tabel"),
                "table_name": semantic_name,
                "raster_row_index": raster_row,
                "table_configured": configured,
                # Distinguishes *why* a table isn't gated by Table Studio's
                # column roles: panel_id being empty means Panel/Table Setup's
                # geometry doesn't recognize where this table sits on this
                # particular source image at all (relation_panel_id() found no
                # containing panel box) -- a different, upstream problem from
                # simply never having opened Table Studio for that panel.
                # Both currently fall back to "let every column through"
                # (relation_column_eligible()'s documented fail-open), so a
                # table with unrecognized geometry silently bypasses even a
                # correctly configured "Overslaan" column.
                "panel_recognized": bool(panel_id),
                # Enforced at save time (both the bulk form and the queue),
                # not here: see the comment above relation_column_eligible().
                # Only meaningful when Panel Setup defines panels at all - a
                # project that has none configured has nothing to be
                # "unrecognized" against.
                "blocked_unrecognized_panel": bool(panel_policy == "block" and not panel_id and panel_by_id),
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

        mappings = database.list_mappings(source_id)
        mappings_by_relation = {
            str(item["relation_id"]): item
            for item in mappings
            if str(item.get("relation_id") or "")
        }
        # Pre-select a label that has been confirmed against exactly one field
        # often enough elsewhere in the project, so a recurring label does not
        # need to be picked by hand on every source (see label_history.py).
        # Only relations without a mapping of their own yet are touched; an
        # existing choice - confirmed or previously overridden - is never
        # second-guessed.
        label_history = label_family_history(
            database.label_history_field_counts(), fields,
            field_family=lambda field: field_lateral_suffix(field) or str(field.get("field_key") or ""),
        )
        known_families = {str(option["family"]) for option in field_options}
        for relation in relations:
            if str(relation.get("relation_id") or "") in mappings_by_relation:
                continue
            suggestion = suggest_family_for_label(str(relation.get("label_text") or ""), label_history)
            if suggestion is None or suggestion[0] not in known_families:
                continue
            relation["auto_suggested_family"] = suggestion[0]
            relation["auto_suggested_count"] = suggestion[1]

        return {
            "source": source,
            "fields": fields,
            "field_options": field_options,
            "relations": relations,
            "relations_by_id": relations_by_id,
            "mappings_by_relation": mappings_by_relation,
            "table_roles_configured": bool(column_roles),
            "panel_policy": panel_policy,
        }

    def _resolve_family_assignment(
        selected: str, relation: dict[str, Any], fields: list[dict[str, Any]]
    ) -> tuple[str, str]:
        """Resolve a posted ``family:<name>`` choice to one concrete field_key.

        Returns ``(field_key, error_message)``; ``error_message`` is empty on
        success. A bare (non-``family:``) value, typically ``""`` for "Niet
        koppelen", passes through unchanged. Shared by the bulk save and the
        one-relation-at-a-time review queue so both apply the exact same
        left/right disambiguation.
        """
        if not selected.startswith("family:"):
            return selected, ""
        family = selected.removeprefix("family:")
        side = relation_lateral_side(relation)
        candidates = [
            field for field in fields
            if (field_lateral_suffix(field) or str(field.get("field_key") or "")) == family
            and (not side or not field_lateral_side(field) or field_lateral_side(field) == side)
        ]
        if len(candidates) != 1:
            return selected, f"Kan algemene veldnaam '{family}' niet eenduidig koppelen aan de gekozen tabel/panel."
        return str(candidates[0]["field_key"]), ""

    def _is_pending(relation_id: str, mappings_by_relation: dict[str, Any]) -> bool:
        return str(mappings_by_relation.get(relation_id, {}).get("status") or "") != "confirmed"

    @app.route("/mapping-labels/<source_id>", methods=["GET", "POST"])
    def label_mapping_studio(source_id: str):
        """Label-first Mapping Studio, independent of ROI review."""
        if request.method == "POST":
            action = str(request.form.get("label_mapping_action") or "save").strip().lower()
            if action == "rebuild":
                job = enqueue_job("20")
                flash("Mappingvoorstellen opnieuw opgebouwd; controleer de nieuwe voorstellen zodra de taak gereed is.", "success")
                return redirect(url_for("label_mapping_studio", source_id=source_id, job_id=job["job_id"]))
            if action == "set_panel_policy":
                policy = str(request.form.get("panel_policy") or "").strip().lower()
                try:
                    save_unrecognized_panel_policy(workspace_root(), policy)
                except ValueError as exc:
                    flash(str(exc), "error")
                else:
                    flash(
                        "Niet-herkende panelen worden nu geblokkeerd voor mapping."
                        if policy == "block" else
                        "Niet-herkende panelen mogen weer gemapt worden (oud gedrag).",
                        "success",
                    )
                return redirect(url_for("label_mapping_studio", source_id=source_id))
            if action != "save":
                abort(400)
            context = _load_label_mapping_context(source_id)
            fields, relations_by_id = context["fields"], context["relations_by_id"]
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
                relation = relations_by_id[assignment["relation_id"]]
                if assignment["field_key"] and relation.get("blocked_unrecognized_panel"):
                    resolution_error = (
                        f"'{relation.get('label_text')}' kan niet gekoppeld worden: Panel Setup herkent deze "
                        "tabel niet op deze bron. Corrigeer Panel Setup, of zet het beleid hierboven op "
                        "'toestaan' als je dit bewust wilt negeren."
                    )
                    break
                resolved, error = _resolve_family_assignment(assignment["field_key"], relation, fields)
                if error:
                    resolution_error = error
                    break
                assignment["field_key"] = resolved
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

        context = _load_label_mapping_context(source_id)
        relations, mappings_by_relation = context["relations"], context["mappings_by_relation"]
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
        pending_count = sum(1 for relation in relations if _is_pending(str(relation["relation_id"]), mappings_by_relation))
        return render_template(
            "mapping_labels_studio.html",
            source=context["source"],
            source_id=source_id,
            sources=_training_pipeline_sources(),
            relations=relations,
            relation_groups=relation_groups,
            mappings_by_relation=mappings_by_relation,
            fields=context["fields"],
            field_options=context["field_options"],
            table_roles_configured=context["table_roles_configured"],
            header_counts={
                "total": len(relations),
                "pending": pending_count,
                "accepted": len(relations) - pending_count,
            },
            header_total_label="labels",
            header_pending_label="te koppelen",
            header_accepted_label="gekoppeld",
            auto_suggested_count=sum(1 for relation in relations if relation.get("auto_suggested_family")),
            queue_start_url=url_for("label_mapping_queue_start", source_id=source_id),
        )

    def _first_pending_in_source(source_id: str) -> str | None:
        context = _load_label_mapping_context(source_id)
        relations, mappings_by_relation = context["relations"], context["mappings_by_relation"]
        first_pending = next(
            (relation for relation in relations if _is_pending(str(relation["relation_id"]), mappings_by_relation)),
            None,
        )
        return str(first_pending["relation_id"]) if first_pending is not None else None

    def _first_pending_in_sources(source_ids: list[str]) -> tuple[str, str] | None:
        """The first (source_id, relation_id) with an open label, in ``source_ids`` order.

        Used both by the global queue entry point and by the queue's own
        auto-advance once a source runs out of pending labels, so working
        through the whole project is one continuous flow: never back to the
        bulk page, never back to the "Bron" dropdown, the same way Stap 5's
        GT Studio moves on to the next source on its own once one is done.
        """
        for candidate_source_id in source_ids:
            relation_id = _first_pending_in_source(candidate_source_id)
            if relation_id is not None:
                return candidate_source_id, relation_id
        return None

    @app.get("/mapping-labels/queue")
    def label_mapping_queue_global_start():
        """Jump straight into the project-wide queue, at the very first open
        label of the first source that has one -- no source needs to be
        picked by hand first.
        """
        all_source_ids = [str(item["source_id"]) for item in _training_pipeline_sources()]
        found = _first_pending_in_sources(all_source_ids)
        if found is None:
            flash("Niets meer te doen: alle bronnen zijn volledig gekoppeld.", "success")
            return redirect(url_for("label_mapping_index"))
        next_source_id, relation_id = found
        return redirect(url_for("label_mapping_queue_item", source_id=next_source_id, relation_id=relation_id))

    @app.get("/mapping-labels/<source_id>/queue")
    def label_mapping_queue_start(source_id: str):
        """Jump into the one-at-a-time review queue at the first pending label."""
        relation_id = _first_pending_in_source(source_id)
        if relation_id is None:
            flash("Niets meer te doen: alle labels van deze bron zijn al gekoppeld.", "success")
            return redirect(url_for("label_mapping_studio", source_id=source_id))
        return redirect(url_for("label_mapping_queue_item", source_id=source_id, relation_id=relation_id))

    @app.route("/mapping-labels/<source_id>/queue/<relation_id>", methods=["GET", "POST"])
    def label_mapping_queue_item(source_id: str, relation_id: str):
        """Review exactly one label at a time: confirm/skip, then jump straight
        to the next pending one, so working through a source's labels never
        requires re-opening the bulk form or re-finding your place in it.
        """
        context = _load_label_mapping_context(source_id)
        fields, relations, relations_by_id = context["fields"], context["relations"], context["relations_by_id"]
        mappings_by_relation = context["mappings_by_relation"]
        relation = relations_by_id.get(relation_id)
        if relation is None:
            abort(404)
        order = [str(item["relation_id"]) for item in relations]
        position = order.index(relation_id)

        def _next_pending_url(after_index: int) -> str | None:
            for candidate_id in order[after_index + 1:]:
                if _is_pending(candidate_id, mappings_by_relation):
                    return url_for("label_mapping_queue_item", source_id=source_id, relation_id=candidate_id)
            return None

        if request.method == "POST":
            queue_action = str(request.form.get("mapping_queue_action") or "confirm").strip().lower()
            selected = "" if queue_action == "skip" else str(request.form.get("field_choice") or "").strip()
            if selected and relation.get("blocked_unrecognized_panel"):
                flash(
                    "Niet opgeslagen: Panel Setup herkent deze tabel niet op deze bron. Corrigeer Panel Setup, "
                    "of zet het beleid in het overzicht op 'toestaan' als je dit bewust wilt negeren.",
                    "error",
                )
                return redirect(url_for("label_mapping_queue_item", source_id=source_id, relation_id=relation_id))
            resolved, error = _resolve_family_assignment(selected, relation, fields)
            if error:
                flash(f"Niet opgeslagen: {error}", "error")
                return redirect(url_for("label_mapping_queue_item", source_id=source_id, relation_id=relation_id))
            try:
                database.sync_relation_mappings(
                    source_id, [{"relation_id": relation_id, "field_key": resolved, "notes": "label-first mapping"}]
                )
            except (KeyError, ValueError) as exc:
                flash(f"Niet opgeslagen: {exc}", "error")
                return redirect(url_for("label_mapping_queue_item", source_id=source_id, relation_id=relation_id))
            next_url = _next_pending_url(position)
            if next_url is not None:
                return redirect(next_url)
            # This source is done: continue the same queue into the next
            # source that still has an open label, instead of dropping back
            # to the bulk page or the "Bron" picker -- see
            # _first_pending_in_sources()'s docstring.
            all_source_ids = [str(item["source_id"]) for item in _training_pipeline_sources()]
            try:
                remaining_source_ids = all_source_ids[all_source_ids.index(source_id) + 1:]
            except ValueError:
                remaining_source_ids = []
            found = _first_pending_in_sources(remaining_source_ids)
            if found is None:
                flash("Alle bronnen zijn doorlopen: geen open labels meer.", "success")
                return redirect(url_for("label_mapping_index"))
            next_source_id, next_relation_id = found
            return redirect(url_for(
                "label_mapping_queue_item", source_id=next_source_id, relation_id=next_relation_id
            ))

        previous_id = order[position - 1] if position > 0 else None
        next_id = order[position + 1] if position + 1 < len(order) else None
        pending_count = sum(1 for rid in order if _is_pending(rid, mappings_by_relation))
        current_mapping = mappings_by_relation.get(relation_id)
        current_family = ""
        if current_mapping and current_mapping.get("field_key"):
            current_family = field_lateral_suffix({"field_key": current_mapping["field_key"]}) or str(current_mapping["field_key"])
        all_sources = _training_pipeline_sources()
        source_index = next(
            (index for index, item in enumerate(all_sources, start=1) if str(item["source_id"]) == source_id), None
        )

        # Visual context, like Stap 9's model-vs-GT comparison: the whole
        # table this label lives in, every one of its rows outlined, the
        # current row highlighted - so confirming a label is "does this
        # yellow box say what I picked" at a glance, not blind label/value
        # text pairs. Only the rows already loaded for this source (i.e.
        # already Table-Studio/eligibility-filtered) are drawn.
        table_id = str(relation.get("table_id") or "")
        table_relations = [item for item in relations if str(item.get("table_id") or "") == table_id]
        source_width = int(context["source"].get("image_width") or 0)
        source_height = int(context["source"].get("image_height") or 0)
        crop = _table_crop_box(table_relations, source_width, source_height) if table_id else None
        table_image_url = (
            url_for("label_mapping_table_image", source_id=source_id, table_id=table_id)
            if crop is not None else None
        )
        image_aspect = f"{crop[2] - crop[0]}/{crop[3] - crop[1]}" if crop is not None else None
        overlays = []
        if crop is not None:
            for item in table_relations:
                item_id = str(item.get("relation_id") or "")
                item_mapping = mappings_by_relation.get(item_id)
                if item_mapping and item_mapping.get("status") == "confirmed":
                    state = "confirmed"
                elif item.get("blocked_unrecognized_panel"):
                    state = "blocked"
                elif item.get("auto_suggested_family"):
                    state = "suggested"
                else:
                    state = "open"
                label_box = None
                if item.get("label_x1") is not None:
                    label_box = (
                        int(item["label_x1"]), int(item["label_y1"]), int(item["label_x2"]), int(item["label_y2"]),
                    )
                value_box = (
                    int(item["value_x1"]), int(item["value_y1"]), int(item["value_x2"]), int(item["value_y2"]),
                )
                overlays.append({
                    "relation_id": item_id,
                    "is_current": item_id == relation_id,
                    "state": state,
                    "label_text": str(item.get("label_text") or ""),
                    "url": url_for("label_mapping_queue_item", source_id=source_id, relation_id=item_id),
                    "label_style": _overlay_box_style(label_box, crop),
                    "value_style": _overlay_box_style(value_box, crop),
                })

        return render_template(
            "mapping_labels_queue.html",
            table_image_url=table_image_url, overlays=overlays, image_aspect=image_aspect,
            source_index=source_index, source_total=len(all_sources),
            source=context["source"],
            source_id=source_id,
            relation=relation,
            field_options=context["field_options"],
            current_family=current_family,
            is_confirmed=bool(current_mapping and current_mapping.get("status") == "confirmed"),
            position=position + 1,
            total=len(order),
            pending_count=pending_count,
            previous_url=(
                url_for("label_mapping_queue_item", source_id=source_id, relation_id=previous_id)
                if previous_id else None
            ),
            next_url=(
                url_for("label_mapping_queue_item", source_id=source_id, relation_id=next_id)
                if next_id else None
            ),
            overview_url=url_for("label_mapping_studio", source_id=source_id),
        )
