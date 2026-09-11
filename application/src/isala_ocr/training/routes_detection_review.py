"""Detection-review routes, split out of webui.create_web_app.

Covers the ``/detection-review`` index and per-source studio pages plus the
``/api/detection-review/...`` mutation endpoints. All state this group needs
(``database``, workspace helpers, mode/strategy predicates and the shared
review-counts helper) is still shared with other route groups defined
directly in webui.py, so it is passed in explicitly rather than
re-implemented here — the same approach used by ``routes_home.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any, Callable

from flask import Flask, abort, jsonify, render_template, request

from .table_cell_ground_truth import (
    add_ground_truth_cell,
    delete_ground_truth_cell,
    ground_truth_counts,
    list_ground_truth_cells,
    list_ground_truth_sources,
    set_ground_truth_source_review_completed,
    update_ground_truth_cell,
)

DETECTION_REVIEW_REASONS = {
    "too_small": "Te klein",
    "too_large": "Te groot",
    "misplaced": "Verkeerd geplaatst",
    "false_positive": "Geen veld / false positive",
    "merged_fields": "Meerdere velden/cellen samengevoegd",
    "split_field": "Eén veld opgesplitst",
    "table_geometry_error": "Tabel/cel fout",
    "other": "Andere reden",
}
DETECTION_RELEVANCE_REASONS = {
    "date_time": "Datum/tijd",
    "ui_element": "UI-element",
    "reference_value": "Referentiewaarde",
    "graph_annotation": "Grafiekannotatie",
    "technical_overlay": "Technische overlay",
    "study_info_out_of_scope": "Patiënt-/studiegegeven buiten huidige scope",
    "other_out_of_scope": "Ander correct veld buiten huidige scope",
}


def register_detection_review_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    canonical_table_gt_mode: Callable[[], bool],
    localization_strategy: Callable[[], str],
    table_panel_state: Callable[[], dict[str, Any]],
    current_table_first_quality: Callable[[], dict[str, Any]],
    table_review_counts: Callable[..., dict[str, int]],
    step4_review_counts: Callable[..., dict[str, int]],
) -> None:
    def detection_review_source_rows() -> list[dict[str, Any]]:
        sources = database.list_detection_sources()
        table_counts = database.detection_table_counts_by_source()
        canonical_sources = {
            str(item["source_id"]): item
            for item in list_ground_truth_sources(workspace_root())
        } if canonical_table_gt_mode() else {}
        if localization_strategy() == "table_first":
            quality = current_table_first_quality()
            candidate_counts = {
                str(item["source_id"]): table_review_counts(str(item["source_id"]), quality)
                for item in sources
            }
        else:
            candidate_counts = database.detection_review_counts_by_source()
        result: list[dict[str, Any]] = []
        for source in sources:
            source_id = str(source["source_id"])
            gt_source = canonical_sources.get(source_id)
            geometry = table_counts.get(source_id, {"regions": 0, "cells": 0})
            is_canonical_gt = gt_source is not None
            counts = ground_truth_counts(workspace_root(), source_id) if is_canonical_gt else candidate_counts.get(source_id, {})
            result.append({
                **source,
                "review_completed": bool(gt_source.get("review_completed", False)) if gt_source else bool(source.get("review_completed", False)),
                "review_completed_at": gt_source.get("review_completed_at") if gt_source else source.get("review_completed_at"),
                "review_counts": counts,
                "table_region_count": int(geometry.get("regions", 0)),
                "table_cell_count": int(geometry.get("cells", 0)),
                "render_exists": safe_workspace_file(str(source.get("render_path") or "")).is_file(),
                "gt_mode": is_canonical_gt,
            })
        return result

    @app.get("/detection-review")
    def detection_review_index():
        rows = detection_review_source_rows()
        gt_mode = canonical_table_gt_mode()
        completed_source_count = sum(1 for row in rows if bool(row.get("review_completed")))
        open_source_count = max(0, len(rows) - completed_source_count)
        return render_template(
            "detection_review_index.html",
            sources=rows, gt_mode=gt_mode,
            completed_source_count=completed_source_count, open_source_count=open_source_count,
            header_counts={
                "total": sum(int(row["review_counts"].get("positive", 0)) for row in rows) if gt_mode else sum(int(row["review_counts"].get("candidate_total", 0)) + int(row["review_counts"].get("added", 0)) for row in rows),
                "pending": 0 if gt_mode else sum(int(row["review_counts"].get("pending", 0)) for row in rows),
                "accepted": sum(int(row["review_counts"].get("positive", 0)) for row in rows),
            },
            review_counts_global={"negative": sum(int(row["review_counts"].get("negative", 0)) for row in rows)},
            header_total_label=("GT-cellen" if gt_mode else "kandidaten"),
            header_pending_label=("open" if gt_mode else "onbeoordeeld"),
            header_accepted_label=("canonieke GT" if gt_mode else "positief"),
        )

    @app.get("/detection-review/<source_id>")
    def detection_review_studio(source_id: str):
        source = database.get_detection_source(source_id)
        if source is None:
            abort(404)
        canonical_gt_sources = {
            str(item.get("source_id") or ""): item
            for item in list_ground_truth_sources(workspace_root())
        } if canonical_table_gt_mode() else {}
        gt_source = canonical_gt_sources.get(source_id)
        gt_mode = gt_source is not None
        if gt_mode:
            source = {
                **source,
                "review_completed": bool(gt_source.get("review_completed", False)),
                "review_completed_at": gt_source.get("review_completed_at"),
            }
        # New sources remain detector-review sources until a reviewer explicitly
        # creates canonical GT. Their model output is never discarded or mistaken
        # for Ground Truth.
        candidates = [] if gt_mode else database.list_detection_candidates(source_id, include_rejected=True)
        annotations = database.list_detection_annotations(source_id, active_only=True, include_ignored=True)
        geometry = database.list_detection_table_geometry(source_id)
        preprocessing_benchmark: dict[str, Any] = {"enabled": False}
        if localization_strategy() == "table_first":
            diagnostic_path = safe_workspace_file(Path("localization_detections") / f"{source_id}.json")
            if diagnostic_path.is_file():
                try:
                    diagnostic_payload = json.loads(diagnostic_path.read_text(encoding="utf-8"))
                    raw_benchmark = diagnostic_payload.get("preprocessing_benchmark")
                    if isinstance(raw_benchmark, dict):
                        preprocessing_benchmark = raw_benchmark
                except (OSError, ValueError, TypeError):
                    pass

        # Structural review assist: infer stable row/column bounds from all Paddle
        # cells. This powers Smart Fit and conservative missing-cell suggestions.
        cell_by_id = {str(item.get("cell_id")): item for item in geometry.get("cells", [])}
        tables_for_assist: dict[str, dict[str, Any]] = {}
        if localization_strategy() == "table_first":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for cell in geometry.get("cells", []):
                grouped.setdefault(str(cell.get("table_id") or ""), []).append(cell)
            for table_id, cells in grouped.items():
                rows: dict[int, list[dict[str, Any]]] = {}
                columns: dict[int, list[dict[str, Any]]] = {}
                for cell in cells:
                    rows.setdefault(int(cell.get("row_index", -1)), []).append(cell)
                    columns.setdefault(int(cell.get("column_index", -1)), []).append(cell)
                multi_rows = {idx: items for idx, items in rows.items() if len(items) >= 2}
                # The structure view must expose every geometrically inferred
                # column, including sparse columns and columns containing a
                # merged cell.  Coverage thresholds are useful for conservative
                # missing-cell suggestions, but must not hide real columns from
                # the structural review.
                canonical_columns = sorted(idx for idx in columns if idx >= 0)
                column_bounds = {
                    idx: [int(round(median([int(c["x1"]) for c in items]))), int(round(median([int(c["x2"]) for c in items])))]
                    for idx, items in columns.items() if idx in canonical_columns
                }
                row_bounds = {
                    idx: [int(round(median([int(c["y1"]) for c in items]))), int(round(median([int(c["y2"]) for c in items])))]
                    for idx, items in rows.items() if idx >= 0
                }
                suggestions: list[dict[str, Any]] = []
                for row_idx, row_cells in multi_rows.items():
                    present = {int(c.get("column_index", -1)) for c in row_cells}
                    for col_idx in canonical_columns:
                        if col_idx in present or col_idx not in column_bounds or row_idx not in row_bounds:
                            continue
                        x1, x2 = column_bounds[col_idx]; y1, y2 = row_bounds[row_idx]
                        if x2 - x1 >= 4 and y2 - y1 >= 4:
                            suggestions.append({
                                "table_id": table_id, "row_index": row_idx, "column_index": col_idx,
                                "x1": x1, "y1": y1, "x2": x2, "y2": y2,
                            })
                tables_for_assist[table_id] = {
                    "canonical_columns": canonical_columns,
                    "column_bounds": column_bounds,
                    "row_bounds": row_bounds,
                    "table_bounds": [
                        min(int(cell["x1"]) for cell in cells), min(int(cell["y1"]) for cell in cells),
                        max(int(cell["x2"]) for cell in cells), max(int(cell["y2"]) for cell in cells),
                    ] if cells else [0, 0, 0, 0],
                    "row_count": len(row_bounds),
                    "column_count": len(canonical_columns),
                    "cell_count": len(cells),
                    "suggestions": suggestions,
                }
        # In legacy detector mode, detached reviewed annotations remain first-class
        # ground truth. In table-first mode, only manual cells added after the
        # current Step-2 detection pass belong to this experiment; older field-box
        # ground truth stays preserved in SQLite but is intentionally hidden here.
        if gt_mode:
            manual_annotations = [
                {
                    **item,
                    "annotation_id": str(item.get("gt_id") or ""),
                    "training_role": "positive",
                    "provenance": str(item.get("provenance") or "canonical_gt"),
                    "candidate_id": "",
                }
                for item in list_ground_truth_cells(workspace_root(), source_id)
            ]
        elif localization_strategy() == "table_first":
            detected_at = str(source.get("detected_at") or "")
            manual_annotations = [
                item for item in annotations
                if not str(item.get("candidate_id") or "")
                and str(item.get("provenance") or "") == "added"
                and (not detected_at or str(item.get("created_at") or "") >= detected_at)
            ]
        else:
            manual_annotations = [item for item in annotations if not str(item.get("candidate_id") or "")]
        for item in candidates:
            status = str(item.get("review_status") or "pending")
            if status == "adjusted":
                item["display_x1"] = int(item.get("corrected_x1") or item["x1"])
                item["display_y1"] = int(item.get("corrected_y1") or item["y1"])
                item["display_x2"] = int(item.get("corrected_x2") or item["x2"])
                item["display_y2"] = int(item.get("corrected_y2") or item["y2"])
            else:
                item["display_x1"] = int(item["x1"]); item["display_y1"] = int(item["y1"])
                item["display_x2"] = int(item["x2"]); item["display_y2"] = int(item["y2"])
            item["review_status"] = status
            item["relevance_status"] = str(item.get("relevance_status") or ("unreviewed" if status == "pending" else "relevant"))
            item["reason_label"] = DETECTION_REVIEW_REASONS.get(str(item.get("reason_code") or ""), "")
            item["relevance_reason_label"] = DETECTION_RELEVANCE_REASONS.get(str(item.get("relevance_reason") or ""), "")
            if localization_strategy() == "table_first":
                cell_id = ""
                for ref in item.get("source_refs") or []:
                    parts = str(ref).split(":")
                    if len(parts) >= 4 and parts[0] == "table" and parts[2] == "cell":
                        cell_id = parts[3]; break
                cell = cell_by_id.get(cell_id) or {}
                item["table_id"] = str(cell.get("table_id") or "")
                item["cell_id"] = cell_id
                item["row_index"] = int(cell.get("row_index", -1))
                item["column_index"] = int(cell.get("column_index", -1))
                assist = tables_for_assist.get(item["table_id"], {})
                rb = (assist.get("row_bounds") or {}).get(item["row_index"])
                cb = (assist.get("column_bounds") or {}).get(item["column_index"])
                item["smart_box"] = [cb[0], rb[0], cb[1], rb[1]] if rb and cb else None
        counts = step4_review_counts(source_id)
        # The canonical GT Studio is the full source-review editor. Keep the
        # compact React page available only as an explicit compatibility view.
        if request.args.get("view", "legacy").strip().lower() != "legacy":
            studio_sources = [
                {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                for item in database.list_detection_sources()
            ]
            return render_template(
                "gt_studio.html", source=source, source_id=source_id,
                candidates=candidates, manual_annotations=manual_annotations,
                sources=studio_sources, gt_mode=gt_mode,
            )
        return render_template(
            "detection_review_studio.html",
            source=source, source_id=source_id, candidates=candidates, gt_mode=gt_mode,
            manual_annotations=manual_annotations,
            table_regions=geometry["regions"], table_cells=geometry["cells"],
            table_assist=tables_for_assist,
            preprocessing_benchmark=preprocessing_benchmark, panel_state=table_panel_state(),
            reconstructed_suggestions=[] if gt_mode else [item for table in tables_for_assist.values() for item in table.get("suggestions", [])],
            reasons=DETECTION_REVIEW_REASONS, relevance_reasons=DETECTION_RELEVANCE_REASONS, review_counts=counts,
            sources=[
                {"source_id": str(item["source_id"]), "review_completed": bool(item.get("review_completed"))}
                for item in database.list_detection_sources()
            ],
            header_counts={
                "total": int(counts.get("positive", 0)) if gt_mode else int(counts.get("candidate_total", 0)) + int(counts.get("added", 0)),
                "pending": 0 if gt_mode else int(counts.get("pending", 0)),
                "accepted": int(counts.get("positive", 0)),
            },
            header_total_label=("GT-cellen" if gt_mode else "kandidaten"), header_pending_label=("open" if gt_mode else "te reviewen"), header_accepted_label="ground truth",
        )

    @app.post("/api/detection-review/<source_id>/<candidate_id>")
    def detection_review_candidate_api(source_id: str, candidate_id: str):
        payload = request.get_json(silent=True) or {}
        status = str(payload.get("status") or "").strip().lower()
        reason = str(payload.get("reason_code") or "").strip().lower()
        relevance_status = str(payload.get("relevance_status") or "relevant").strip().lower()
        relevance_reason = str(payload.get("relevance_reason") or "").strip().lower()
        notes = str(payload.get("notes") or "")[:2000]
        box_payload = payload.get("box")
        corrected_box = None
        if isinstance(box_payload, list) and len(box_payload) == 4:
            corrected_box = tuple(int(round(float(value))) for value in box_payload)
        try:
            item = database.review_detection_candidate(
                source_id=source_id, candidate_id=candidate_id, review_status=status,
                corrected_box=corrected_box, reason_code=reason,
                relevance_status=relevance_status, relevance_reason=relevance_reason, notes=notes,
            )
        except KeyError:
            return jsonify({"ok": False, "error": "Kandidaat niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "candidate": item, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/batch")
    def detection_review_batch_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        raw_ids = payload.get("candidate_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "error": "candidate_ids moet een lijst zijn"}), 400
        candidate_ids = []
        seen = set()
        for raw in raw_ids:
            candidate_id = str(raw or "").strip()
            if candidate_id and candidate_id not in seen:
                candidate_ids.append(candidate_id); seen.add(candidate_id)
        if not candidate_ids:
            return jsonify({"ok": False, "error": "Selecteer minimaal één kandidaat"}), 400
        if len(candidate_ids) > 2000:
            return jsonify({"ok": False, "error": "Maximaal 2000 kandidaten per batch"}), 400
        operation = str(payload.get("operation") or "").strip().lower()
        if operation not in {"confirm", "reject", "irrelevant", "relevant"}:
            return jsonify({"ok": False, "error": "Onbekende batchactie"}), 400
        reason = str(payload.get("reason_code") or "").strip().lower()
        relevance_reason = str(payload.get("relevance_reason") or "").strip().lower()
        notes = str(payload.get("notes") or "")[:2000]
        if reason and reason not in DETECTION_REVIEW_REASONS:
            return jsonify({"ok": False, "error": "Onbekende detectiereden"}), 400
        if relevance_reason and relevance_reason not in DETECTION_RELEVANCE_REASONS:
            return jsonify({"ok": False, "error": "Onbekende relevantieregel"}), 400
        current = {str(item["candidate_id"]): item for item in database.list_detection_candidates(source_id, include_rejected=True)}
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in current]
        if missing:
            return jsonify({"ok": False, "error": f"Kandidaat niet gevonden: {missing[0]}"}), 404
        updated = []
        try:
            for candidate_id in candidate_ids:
                candidate = current[candidate_id]
                current_status = str(candidate.get("review_status") or "pending")
                preserve_adjusted = current_status == "adjusted"
                corrected_box = None
                if preserve_adjusted:
                    corrected_box = (
                        int(candidate.get("corrected_x1") or candidate["x1"]),
                        int(candidate.get("corrected_y1") or candidate["y1"]),
                        int(candidate.get("corrected_x2") or candidate["x2"]),
                        int(candidate.get("corrected_y2") or candidate["y2"]),
                    )
                if operation == "reject":
                    status, relevance, scope_reason = "rejected", "unreviewed", ""
                    review_reason = reason
                elif operation == "irrelevant":
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "irrelevant", relevance_reason
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                elif operation == "relevant":
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "relevant", ""
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                else:
                    status = "adjusted" if preserve_adjusted else "correct"
                    relevance, scope_reason = "relevant", ""
                    review_reason = str(candidate.get("reason_code") or "") if preserve_adjusted else ""
                updated.append(database.review_detection_candidate(
                    source_id=source_id, candidate_id=candidate_id, review_status=status,
                    corrected_box=corrected_box, reason_code=review_reason,
                    relevance_status=relevance, relevance_reason=scope_reason,
                    notes=notes if notes else str(candidate.get("review_notes") or ""),
                ))
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "updated": len(updated), "candidates": updated, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/complete")
    def detection_review_complete_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        completed = bool(payload.get("completed", True))
        try:
            if canonical_table_gt_mode():
                source = set_ground_truth_source_review_completed(workspace_root(), source_id, completed)
            else:
                source = database.set_detection_source_review_completed(source_id, completed)
        except (KeyError, FileNotFoundError):
            return jsonify({"ok": False, "error": "Bron niet gevonden"}), 404
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc), "counts": step4_review_counts(source_id)}), 409
        return jsonify({
            "ok": True,
            "completed": bool(source.get("review_completed")),
            "review_completed_at": source.get("review_completed_at"),
            "counts": step4_review_counts(source_id),
        })

    @app.post("/api/detection-review/<source_id>/manual")
    def detection_review_manual_api(source_id: str):
        payload = request.get_json(silent=True) or {}
        box_payload = payload.get("box")
        if not isinstance(box_payload, list) or len(box_payload) != 4:
            return jsonify({"ok": False, "error": "box moet vier coördinaten bevatten"}), 400
        try:
            box = tuple(int(round(float(value))) for value in box_payload)
            if canonical_table_gt_mode():
                gt = add_ground_truth_cell(workspace_root(), source_id, box)
                item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "manual_gt")}
            else:
                item = database.add_detection_annotation(
                    source_id=source_id, box=box,
                    reason_code=str(payload.get("reason_code") or "other"),
                    notes=str(payload.get("notes") or "")[:2000],
                )
        except KeyError:
            return jsonify({"ok": False, "error": "Bron niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "annotation": item, "counts": step4_review_counts(source_id)})

    @app.post("/api/detection-review/<source_id>/<candidate_id>/promote-to-gt")
    def detection_review_promote_candidate_to_gt_api(source_id: str, candidate_id: str):
        """Promote one reviewed table-cell proposal to canonical GT."""
        candidate = database.get_detection_candidate(source_id, candidate_id)
        if candidate is None:
            return jsonify({"ok": False, "error": "Kandidaat niet gevonden"}), 404
        box = (
            int(candidate.get("corrected_x1") or candidate["x1"]),
            int(candidate.get("corrected_y1") or candidate["y1"]),
            int(candidate.get("corrected_x2") or candidate["x2"]),
            int(candidate.get("corrected_y2") or candidate["y2"]),
        )
        try:
            gt = add_ground_truth_cell(workspace_root(), source_id, box, provenance="step7_prediction_gt")
            database.review_detection_candidate(
                source_id=source_id, candidate_id=candidate_id, review_status="correct",
                relevance_status="relevant", reason_code="", relevance_reason="",
                notes="Promoted to canonical GT",
            )
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "step7_prediction_gt")}
        return jsonify({"ok": True, "annotation": item, "counts": ground_truth_counts(workspace_root(), source_id)})

    @app.post("/api/detection-review/<source_id>/accept-unreviewed")
    def detection_review_accept_unreviewed_api(source_id: str):
        return jsonify({
            "ok": False,
            "error": "Impliciet accepteren is uitgeschakeld. Alleen expliciet beoordeelde crops worden trainingsdata.",
        }), 410

    @app.post("/api/detection-review/accept-all-unreviewed")
    def detection_review_accept_all_unreviewed_api():
        return jsonify({
            "ok": False,
            "error": "Impliciet accepteren is uitgeschakeld. Onbeoordeelde kandidaten worden bewust genegeerd.",
        }), 410

    @app.patch("/api/detection-review/<source_id>/manual/<annotation_id>")
    def detection_review_update_manual_api(source_id: str, annotation_id: str):
        payload = request.get_json(silent=True) or {}
        box_payload = payload.get("box")
        if not isinstance(box_payload, list) or len(box_payload) != 4:
            return jsonify({"ok": False, "error": "box moet vier coördinaten bevatten"}), 400
        try:
            box = tuple(int(round(float(value))) for value in box_payload)
            if canonical_table_gt_mode():
                gt = update_ground_truth_cell(workspace_root(), source_id, annotation_id, box)
                item = {**gt, "annotation_id": gt["gt_id"], "training_role": "positive", "provenance": gt.get("provenance", "canonical_gt")}
            else:
                item = database.update_manual_detection_annotation(annotation_id, box=box)
                if str(item.get("source_id") or "") != source_id:
                    return jsonify({"ok": False, "error": "Handmatige annotatie hoort bij een andere bron"}), 409
        except KeyError:
            return jsonify({"ok": False, "error": "Handmatige annotatie niet gevonden"}), 404
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({
            "ok": True,
            "annotation": item,
            "counts": step4_review_counts(source_id),
        })

    @app.delete("/api/detection-review/<source_id>/manual/<annotation_id>")
    def detection_review_delete_manual_api(source_id: str, annotation_id: str):
        try:
            if canonical_table_gt_mode():
                delete_ground_truth_cell(workspace_root(), source_id, annotation_id)
            else:
                database.delete_manual_detection_annotation(annotation_id)
        except KeyError:
            return jsonify({"ok": False, "error": "Ground Truth-cel niet gevonden" if canonical_table_gt_mode() else "Handmatige annotatie niet gevonden"}), 404
        return jsonify({"ok": True, "counts": step4_review_counts(source_id)})
