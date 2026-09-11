"""Reactive /api/v2/localization/* and /api/v2/jobs, /api/v2/events routes,
split out of webui.create_web_app.

This is the JSON/SSE API surface the React localization-workbench and
quality screens poll. The payload-builder helpers
(``localization_readiness_payload``, ``preparation_for_current_strategy``,
``localization_workbench_payload``, ``localization_quality_payload``,
``localization_artifacts_payload``, ``save_localization_artifact_selection``,
``select_localization_work_dataset``, ``artifact_delete_plan``,
``enqueue_artifact_delete_job``, ``localization_event_signature``) all stay
in webui.py: each is also called from other route groups and/or from each
other, so they are genuinely shared state/business-logic, not
route-group-local helpers. They are passed in explicitly instead, same as
``job_statuses``/``enqueue_job``/``current_recognition_gate``/``ACTIONS``.

``localization_evaluation_details``, ``localization_dataset_image_path``
and ``save_localization_split_config`` are pure functions imported
directly from ``localization_dataset.py`` (not from webui.py), so no
circular import risk there.
"""

from __future__ import annotations

import json
import re
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from flask import Flask, Response, abort, jsonify, request, send_file, stream_with_context

from .localization_dataset import (
    localization_dataset_image_path,
    localization_evaluation_details,
    save_localization_split_config,
)


def register_localization_v2_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    localization_readiness_payload: Callable[[], dict[str, Any]],
    preparation_for_current_strategy: Callable[[], dict[str, Any]],
    localization_workbench_payload: Callable[[], dict[str, Any]],
    localization_quality_payload: Callable[[], dict[str, Any]],
    localization_artifacts_payload: Callable[[], dict[str, Any]],
    save_localization_artifact_selection: Callable[[dict[str, Any]], dict[str, Any]],
    select_localization_work_dataset: Callable[[str], dict[str, Any]],
    artifact_delete_plan: Callable[..., dict[str, Any]],
    enqueue_artifact_delete_job: Callable[..., dict[str, Any]],
    localization_event_signature: Callable[[], str],
    job_statuses: Callable[..., list[dict[str, Any]]],
    enqueue_job: Callable[..., dict[str, Any]],
    current_recognition_gate: Callable[[], dict[str, Any]],
    actions: dict[str, str],
    utcnow: Callable[[], str],
) -> None:
    @app.get("/api/localization-readiness")
    def api_localization_readiness():
        """Backward-compatible readiness endpoint for legacy screens."""
        return jsonify(localization_readiness_payload())

    @app.get("/api/v2/preparation")
    def api_v2_preparation():
        return jsonify({"ok": True, "preparation": preparation_for_current_strategy()})

    @app.get("/api/v2/localization/workbench")
    def api_v2_localization_workbench():
        response = jsonify(localization_workbench_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality")
    def api_v2_localization_quality():
        response = jsonify(localization_quality_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality/details")
    def api_v2_localization_quality_details():
        evaluation_id = str(request.args.get("evaluation_id") or "").strip()
        if not evaluation_id:
            return jsonify({"ok": False, "error": "Kies eerst een getrainde evaluatie."}), 400
        evaluation = database.get_localization_evaluation(evaluation_id)
        if evaluation is None or str(evaluation.get("kind") or "") != "trained":
            return jsonify({"ok": False, "error": "De gekozen getrainde evaluatie bestaat niet meer."}), 404
        predictions_path = str(evaluation.get("predictions_path") or "").strip()
        if not predictions_path:
            return jsonify({
                "ok": False,
                "error": "Deze evaluatie bevat geen bewaarde voorspellingen. Voer Nieuwe evaluatie uitvoeren opnieuw uit om visuele diagnostiek te maken.",
            }), 409
        try:
            confidence = float(request.args.get("threshold") or (evaluation.get("metrics") or {}).get("minimum_confidence") or 0.25)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Ongeldige confidence-threshold."}), 400
        confidence = max(0.0, min(1.0, confidence))
        split = str(request.args.get("split") or evaluation.get("split") or "test").strip().lower()
        if split not in {"train", "val", "test"}:
            return jsonify({"ok": False, "error": "Split moet train, val of test zijn."}), 400
        try:
            iou_threshold = float(request.args.get("iou") or request.args.get("iou_threshold") or (evaluation.get("metrics") or {}).get("iou_threshold") or 0.75)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Ongeldige IoU-drempel."}), 400
        iou_threshold = max(0.05, min(0.95, iou_threshold))
        try:
            details = localization_evaluation_details(
                workspace_root(), predictions_path,
                model_id=str(evaluation.get("model_id") or ""),
                dataset_id=str(evaluation.get("dataset_id") or ""),
                minimum_confidence=confidence,
                iou_threshold=iou_threshold,
                canonical_iou_threshold=float((evaluation.get("metrics") or {}).get("iou_threshold") or 0.75),
                split=split,
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        except Exception as exc:
            # This is a localhost-only diagnostic endpoint. Never turn a useful
            # visualization failure into an opaque HTTP 500: surface the concrete
            # exception while keeping the page alive so the reviewer knows what to fix.
            traceback.print_exc()
            return jsonify({
                "ok": False,
                "error": f"Visuele diagnostiek kon niet worden opgebouwd: {type(exc).__name__}: {exc}",
            }), 500
        response = jsonify({"ok": True, "evaluation_id": evaluation_id, "details": details})
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/v2/localization/quality/image/<dataset_id>/<source_id>")
    def api_v2_localization_quality_image(dataset_id: str, source_id: str):
        split = str(request.args.get("split") or "test").strip().lower()
        if split not in {"train", "val", "test"}:
            abort(400)
        try:
            path = localization_dataset_image_path(
                workspace_root(), dataset_id=dataset_id, source_id=source_id, split=split
            )
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            abort(404)
        response = send_file(path, conditional=True, max_age=3600)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    @app.get("/api/v2/localization/artifacts")
    def api_v2_localization_artifacts():
        response = jsonify(localization_artifacts_payload())
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.post("/api/v2/localization/selection")
    def api_v2_localization_selection():
        payload = request.get_json(silent=True) or {}
        try:
            selection = save_localization_artifact_selection(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "selection": selection, "quality": localization_quality_payload()})

    @app.post("/api/v2/localization/datasets/select")
    def api_v2_localization_select_dataset():
        payload = request.get_json(silent=True) or {}
        try:
            readiness = select_localization_work_dataset(str(payload.get("dataset_id") or ""))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "readiness": readiness, "artifacts": localization_artifacts_payload()})

    @app.post("/api/v2/localization/artifacts/delete")
    def api_v2_localization_delete_artifact():
        payload = request.get_json(silent=True) or {}
        kind = str(payload.get("kind") or "")
        artifact_id = str(payload.get("id") or "")
        cascade = bool(payload.get("cascade"))
        replacement_dataset_id = str(payload.get("replacement_dataset_id") or "")
        try:
            plan = artifact_delete_plan(
                kind, artifact_id, replacement_dataset_id=replacement_dataset_id
            )
            if bool(plan.get("requires_cascade")) and not cascade:
                if str(plan.get("kind") or kind) == "model":
                    raise ValueError(
                        f"Model wordt gebruikt door {int(plan.get('dependency_count') or 0)} evaluatie(s); "
                        "verwijder die eerst of gebruik cascade"
                    )
                raise ValueError(
                    f"Dataset heeft {int(plan.get('dependency_count') or 0)} afhankelijke model/evaluatie-artifact(s); "
                    "verwijder die eerst of gebruik cascade"
                )
            job = enqueue_artifact_delete_job(
                kind, artifact_id, cascade=cascade, replacement_dataset_id=replacement_dataset_id
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        return jsonify({
            "ok": True,
            "queued": True,
            "job_id": str(job.get("job_id") or ""),
            "status": str(job.get("status") or "pending"),
            "plan": plan,
        }), 202

    @app.post("/api/v2/localization/split")
    def api_v2_localization_split():
        payload = request.get_json(silent=True) or {}
        action = str(payload.get("action") or "save").strip().lower()
        try:
            if action == "auto":
                plan = save_localization_split_config(workspace_root(), mode="auto", overrides={})
            elif action == "save":
                raw_targets = payload.get("targets") if isinstance(payload.get("targets"), dict) else {}
                targets = {
                    "train": int(raw_targets.get("train") or 0),
                    "val": int(raw_targets.get("val") or 0),
                    "test": int(raw_targets.get("test") or 0),
                }
                raw_overrides = payload.get("overrides") if isinstance(payload.get("overrides"), dict) else {}
                overrides = {
                    str(source_id): str(split)
                    for source_id, split in raw_overrides.items()
                    if str(split) in {"train", "val", "test"}
                }
                plan = save_localization_split_config(
                    workspace_root(), mode="counts", targets=targets, overrides=overrides
                )
            else:
                return jsonify({"ok": False, "error": "Onbekende splitactie"}), 400
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "plan": plan, "workbench": localization_workbench_payload()})

    @app.post("/api/v2/jobs")
    def api_v2_create_job():
        payload = request.get_json(silent=True) or {}
        action_id = str(payload.get("action_id") or "").strip()
        if action_id not in actions:
            return jsonify({"ok": False, "error": "Onbekende taak"}), 400
        if action_id in {"24", "25", "26", "27", "28"} and not current_recognition_gate().get("ready"):
            gate = current_recognition_gate()
            return jsonify({"ok": False, "error": f"Recognition is vergrendeld: {gate.get('reason') or 'goedgekeurde Recognition-GT ontbreekt'}."}), 423
        # Prevent double-submit races from a reactive UI. Existing jobs remain
        # selectable in the terminal dock and the client can retry after they finish.
        existing = next((
            item for item in job_statuses(20, action_ids={action_id})
            if str(item.get("status") or "") in {"pending", "running"}
        ), None)
        if existing is not None:
            return jsonify({"ok": False, "error": "Deze taak draait al.", "job": existing}), 409
        options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
        if action_id == "2" and options.get("table_model_id") is not None:
            table_model_id = str(options.get("table_model_id") or "").strip()
            if table_model_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}", table_model_id):
                return jsonify({"ok": False, "error": "Ongeldig table-cell model-ID"}), 400
            options = {**options, "table_model_id": table_model_id}
        if action_id in {"9", "10", "11"}:
            # Persist resolved defaults so the non-interactive PowerShell worker
            # sees exactly the same dataset/model selection as the React client.
            # A fresh evaluate+compare run intentionally resets manual evaluation
            # pinning so the newly produced pair becomes visible immediately.
            if action_id == "9":
                save_localization_artifact_selection({"baseline_evaluation_id": "", "trained_evaluation_id": ""})
            else:
                save_localization_artifact_selection({})
        if action_id == "26":
            device = str(options.get("device") or "gpu").strip().lower()
            if device not in {"cpu", "gpu"}:
                return jsonify({"ok": False, "error": "Ongeldig device"}), 400
            options = {**options, "device": device}
        job = enqueue_job(action_id, options)
        return jsonify({"ok": True, "job": job}), 202

    @app.get("/api/v2/events")
    def api_v2_events():
        """SSE invalidation stream for reactive screens.

        It sends tiny invalidation messages rather than complete snapshots. The
        client then refetches only the state it owns, so no page navigation or
        full HTML refresh is necessary.
        """
        @stream_with_context
        def event_stream():
            last_signature = ""
            last_heartbeat = time.monotonic()
            yield "event: connected\ndata: {\"scope\":\"all\"}\n\n"
            while True:
                signature = localization_event_signature()
                if signature != last_signature:
                    last_signature = signature
                    data = json.dumps({
                        "scope": "all",
                        "at": utcnow(),
                    }, ensure_ascii=False)
                    yield f"event: invalidate\ndata: {data}\n\n"
                    last_heartbeat = time.monotonic()
                elif time.monotonic() - last_heartbeat >= 15:
                    yield ": keep-alive\n\n"
                    last_heartbeat = time.monotonic()
                time.sleep(1.0)

        response = Response(event_stream(), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response
