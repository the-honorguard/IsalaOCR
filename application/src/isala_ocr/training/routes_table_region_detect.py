"""Table-region (re)detection trigger routes, split out of
webui.create_web_app.

These were deliberately left behind when routes_table_panel_config.py
was extracted, because they enqueue jobs on the shared filesystem job
queue and touch ``loaded_config``/``prepare_source_renders``. Both are
used by several other route groups too, so - same pattern as
elsewhere - they are passed in explicitly rather than moved.

``prepare_source_renders`` is a pure function imported directly from
``source_preview.py`` (not from webui.py), so no circular import risk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, request

from .source_preview import prepare_source_renders

_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


def register_table_region_detect_routes(
    app: Flask,
    *,
    workspace_root: Callable[[], Path],
    enqueue_job: Callable[..., dict[str, Any]],
    loaded_config: Any | None,
    record_webui_error: Callable[..., str],
) -> None:
    @app.post("/api/table-region-redetect")
    def table_region_redetect_api():
        source_id = str((request.get_json(silent=True) or {}).get("source_id") or "").strip()
        if not source_id:
            return jsonify({"error": "source_id is verplicht"}), 400
        payload = enqueue_job("59", action_name="Tabelregio’s opnieuw detecteren voor beoordeling")
        return jsonify({"ok": True, "job": payload, "message": "Nieuwe voorspelling gestart; bestaande handmatige GT blijft bewaard."}), 202

    @app.post("/api/table-region-detect")
    def table_region_detect_api():
        if loaded_config is None:
            return jsonify({"error": "De actieve configuratie ontbreekt"}), 409
        try:
            result = prepare_source_renders("/input", workspace_root(), loaded_config)
        except Exception as exc:
            record_webui_error("source_render_prepare_for_table_detection", exc)
            return jsonify({"error": f"Bronrenders konden niet worden voorbereid: {type(exc).__name__}: {exc}"}), 500
        payload = enqueue_job("59", action_name="Tabelregio’s detecteren voor beoordeling")
        return jsonify({"ok": True, "job": payload, "sources": result.get("sources", 0), "message": "Bronrenders voorbereid; alleen tabelregio-detectie gestart."}), 202

    @app.post("/api/table-region-detect-source")
    def table_region_detect_source_api():
        if loaded_config is None:
            return jsonify({"error": "De actieve configuratie ontbreekt"}), 409
        source_id = str((request.get_json(silent=True) or {}).get("source_id") or "").strip()
        if not _SOURCE_ID_RE.fullmatch(source_id):
            return jsonify({"error": "Ongeldig source_id"}), 400
        try:
            prepare_source_renders("/input", workspace_root(), loaded_config)
        except Exception as exc:
            record_webui_error("source_render_prepare_for_single_table_detection", exc)
            return jsonify({"error": f"Bronrenders konden niet worden voorbereid: {type(exc).__name__}: {exc}"}), 500
        payload = enqueue_job(
            "59",
            {"source_id": source_id},
            action_name="Alleen huidige bron · tabelregio’s detecteren",
        )
        return jsonify({"ok": True, "job": payload, "message": f"Alleen bron {source_id} opnieuw op tabelregio’s detecteren gestart."}), 202
