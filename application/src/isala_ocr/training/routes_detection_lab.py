"""TEMPORARY detection-lab routes ("Detectie-lab") for the cell-merging
regression investigation: compare three candidate fixes side by side on one
already-rendered source image, without running the full Stap 5 batch job.

Background: activating a trained table-region model makes
``PPStructureTableEngine.detect_with_benchmark`` skip the preprocessing
variant trial entirely (see ``detect_with_trained_regions`` in
``ocr/table_structure.py``), which is a plausible cause of cells that keep
merging across faint row/column borders no matter how often detection is
re-run. This page runs three approaches on one source and shows the
resulting cell overlays + geometry scores next to each other:

  1. "Probeer 1": force the full preprocessing-variant benchmark (original,
     grayscale, CLAHE, inverted CLAHE, adaptive threshold), ignoring any
     active trained region model.
  2. "Probeer 2": keep the trained region model's boxes, but re-add a
     preprocessing-variant trial inside each region instead of a single pass.
  3. "Probeer 3": detect faint row-to-row contrast steps and draw a
     reinforcing line at each one before a single detection pass.

The ``labeler`` container this module runs in deliberately does not install
PaddleOCR/PaddlePaddle (see ``infrastructure/docker/Dockerfile.labeler``), so
the actual detection work cannot run in-process here. Instead this module
only renders the page, enqueues job action "62" (via the existing job queue -
see ``create_job`` in ``routes_jobs.py``, and ``detection_lab_cli.py`` /
``webui-worker.ps1`` for where the job actually runs), and serves the
overlay images + results JSON that job writes into the shared workspace.

This module, its template, its CLI counterpart (``isala_ocr.detection_lab_cli``)
and its sidebar link are intentionally scoped as a throwaway experiment -
remove all of it once the regression is understood and one approach has been
folded into the real pipeline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from flask import Flask, abort, jsonify, render_template, request, send_file

from .collector import _table_settings_with_active_region_model
from .table_cell_training import list_table_cell_models

_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\.png")


def register_detection_lab_routes(
    app: Flask,
    *,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    database: Any,
    loaded_config: Any,
    record_webui_error: Callable[..., str],
) -> None:
    def _table_settings() -> dict[str, Any]:
        if loaded_config is None:
            return {}
        raw = dict(
            loaded_config.raw.get("training", {}).get("collection", {}).get("table_structure", {}) or {}
        )
        return _table_settings_with_active_region_model(workspace_root(), raw)

    @app.get("/detection-lab")
    def detection_lab_page():
        sources = database.list_detection_sources()
        active_region_model = str(_table_settings().get("table_region_model_dir") or "").strip()
        return render_template(
            "detection_lab.html",
            sources=sources,
            active_region_model=bool(active_region_model),
            selected_source_id=request.args.get("source_id") or (sources[0]["source_id"] if sources else ""),
            table_cell_models=list_table_cell_models(workspace_root()),
            selected_table_model_id=request.args.get("table_model_id") or "active",
        )

    @app.get("/api/detection-lab/results/<source_id>")
    def detection_lab_results(source_id: str):
        if not _SOURCE_ID_RE.fullmatch(source_id):
            abort(404)
        results_path = safe_workspace_file(Path("detection_lab") / f"{source_id}-results.json")
        if not results_path.is_file():
            return jsonify({"ok": False, "error": "Nog geen resultaten voor deze bron."}), 404
        try:
            payload = json.loads(results_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            record_webui_error("detection_lab_results", exc)
            return jsonify({"ok": False, "error": "Resultatenbestand kon niet worden gelezen."}), 500
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, dict):
            return jsonify({"ok": False, "error": "Ongeldig resultatenbestand."}), 500
        for entry in results.values():
            if not isinstance(entry, dict):
                continue
            image_file = str(entry.get("image_file") or "").strip()
            if image_file and _FILENAME_RE.fullmatch(image_file):
                entry["image_url"] = f"/detection-lab-image/{image_file}"
        return jsonify({
            "ok": True,
            "source_id": str(payload.get("source_id") or source_id),
            "generated_at": payload.get("generated_at"),
            "results": results,
        })

    @app.get("/detection-lab-image/<path:filename>")
    def detection_lab_image(filename: str):
        if not _FILENAME_RE.fullmatch(filename):
            abort(404)
        path = safe_workspace_file(Path("detection_lab") / filename)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)
