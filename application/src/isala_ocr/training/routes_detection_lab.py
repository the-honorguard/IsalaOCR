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

This module, its template and its sidebar link are intentionally scoped as a
throwaway experiment - remove all three once the regression is understood
and one approach has been folded into the real pipeline.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

import cv2
from flask import Flask, abort, jsonify, render_template, request, send_file

from ..config import AppConfig
from ..ocr.table_structure import PPStructureTableEngine, score_table_structure
from .collector import _table_settings_with_active_region_model

_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_FILENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\.png")
_APPROACHES = {"forced_benchmark", "region_variant_trial", "contrast_lines"}
_APPROACH_LABELS = {
    "forced_benchmark": "Probeer 1 · Volledige benchmark (regio-model genegeerd)",
    "region_variant_trial": "Probeer 2 · Regio-model + variant-trial per regio",
    "contrast_lines": "Probeer 3 · Contrastlijnen tussen rijen",
}


def register_detection_lab_routes(
    app: Flask,
    *,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    database: Any,
    loaded_config: AppConfig | None,
    record_webui_error: Callable[..., str],
) -> None:
    def _table_settings() -> dict[str, Any]:
        if loaded_config is None:
            return {}
        raw = dict(
            loaded_config.raw.get("training", {}).get("collection", {}).get("table_structure", {}) or {}
        )
        return _table_settings_with_active_region_model(workspace_root(), raw)

    def _draw_cell_overlay(image, regions):
        canvas = image.copy()
        for region in regions:
            box = region.box
            cv2.rectangle(canvas, (box.x1, box.y1), (box.x2, box.y2), (0, 140, 255), 2)
            for cell in region.cells:
                cbox = cell.box
                cv2.rectangle(canvas, (cbox.x1, cbox.y1), (cbox.x2, cbox.y2), (0, 220, 0), 1)
        return canvas

    @app.get("/detection-lab")
    def detection_lab_page():
        sources = database.list_detection_sources()
        active_region_model = str(_table_settings().get("table_region_model_dir") or "").strip()
        return render_template(
            "detection_lab.html",
            sources=sources,
            active_region_model=bool(active_region_model),
            selected_source_id=request.args.get("source_id") or (sources[0]["source_id"] if sources else ""),
        )

    @app.post("/api/detection-lab/run")
    def detection_lab_run():
        payload = request.get_json(silent=True) or {}
        source_id = str(payload.get("source_id") or "").strip()
        approach = str(payload.get("approach") or "").strip()
        if approach not in _APPROACHES:
            return jsonify({"error": "Onbekende aanpak"}), 400
        if not _SOURCE_ID_RE.fullmatch(source_id):
            return jsonify({"error": "Ongeldig source_id"}), 400
        render_path = safe_workspace_file(Path("source_renders") / f"{source_id}.png")
        if not render_path.is_file():
            return jsonify({"error": "Geen bronrender gevonden; draai eerst Stap 4/5 voor deze bron."}), 404
        image = cv2.imread(str(render_path))
        if image is None:
            return jsonify({"error": "Bronrender kon niet worden gelezen"}), 500
        if loaded_config is None:
            return jsonify({"error": "De actieve configuratie ontbreekt"}), 409
        try:
            engine = PPStructureTableEngine(loaded_config.ocr, _table_settings())
            engine.warmup()
            if approach == "forced_benchmark":
                regions, diagnostics = engine.detect_with_forced_full_benchmark(image, source_id=source_id)
            elif approach == "region_variant_trial":
                regions, diagnostics = engine.detect_with_trained_regions_benchmark(image, source_id=source_id)
            else:
                regions, diagnostics = engine.detect_with_contrast_lines(image, source_id=source_id)
        except Exception as exc:
            record_webui_error("detection_lab_run", exc)
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500
        metrics = score_table_structure(regions)
        overlay = _draw_cell_overlay(image, regions)
        out_dir = workspace_root() / "detection_lab"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{source_id}-{approach}-{int(time.time() * 1000)}.png"
        out_path = out_dir / filename
        if not cv2.imwrite(str(out_path), overlay):
            return jsonify({"error": "Overlay kon niet worden opgeslagen"}), 500
        return jsonify({
            "ok": True,
            "approach": approach,
            "label": _APPROACH_LABELS.get(approach, approach),
            "image_url": f"/detection-lab-image/{filename}",
            "metrics": metrics,
            "diagnostics": {key: value for key, value in diagnostics.items() if key not in ("runs", "regions")},
        })

    @app.get("/detection-lab-image/<path:filename>")
    def detection_lab_image(filename: str):
        if not _FILENAME_RE.fullmatch(filename):
            abort(404)
        path = safe_workspace_file(Path("detection_lab") / filename)
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype="image/png", max_age=0)
