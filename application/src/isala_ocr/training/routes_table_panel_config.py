"""Table-panel definition/geometry and table-semantics JSON APIs, split
out of webui.create_web_app.

Only the pure, read/write-to-disk endpoints of this group move here.
``/api/table-region-redetect``, ``/api/table-region-detect`` and
``/api/table-region-detect-source`` stay in webui.py because they
enqueue jobs on the shared filesystem job queue (``enqueue_job``) and
touch ``loaded_config``/``prepare_source_renders`` - deliberately left
alone until that state is threaded through an explicit services object
rather than picked up piecemeal here.

The shared helpers this module's routes use (the active project
``database`` proxy, ``workspace_root`` and ``safe_workspace_file``)
stay in webui.py and are passed in explicitly. Everything else here
(``save_panel_definitions``, ``save_panel_profile``,
``clear_panel_geometry``, ``load_panel_profile``,
``clear_table_regions``, ``save_table_regions``,
``build_table_region_dataset``, ``save_table_semantic_assignment``,
``normalize_for_matching``) is a pure module-level function imported
directly.
"""

from __future__ import annotations

import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

import cv2
from flask import Flask, jsonify, request

from .dynamic_locator import normalize_for_matching
from .json_api import json_body
from .table_panels import clear_panel_geometry, load_panel_profile, save_panel_definitions, save_panel_profile
from .table_region_ground_truth import clear_table_regions, save_table_regions
from .table_region_training import build_table_region_dataset
from .table_semantics import save_assignment as save_table_semantic_assignment

_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")


def register_table_panel_config_routes(
    app: Flask,
    *,
    database: Any,
    workspace_root: Callable[[], Path],
    safe_workspace_file: Callable[[str | Path], Path],
    cached_render_image: Callable[[Path], Any],
) -> None:
    _table_semantic_ocr_cache: dict[tuple[Any, ...], str] = {}
    _table_semantic_ocr_cache_lock = threading.Lock()

    def _ocr_text_for_region(render_path: Path, source_id: str, box: tuple[float, float, float, float]) -> str:
        """Run tesseract on one table-semantic-detect region, cached.

        table_semantic_detect_api() used to run this synchronously, once per
        region needing the OCR fallback, directly in the request thread -
        the same blocking-subprocess-per-item pattern already fixed for
        Panel Setup's quick_ocr_text_for_proposal() (webui.py). Cache per
        (source, box, render identity) and reuse the shared
        cached_render_image() helper instead of re-decoding the render PNG
        once per region; callers run the remaining cache misses in parallel.
        """
        rx1, ry1, rx2, ry2 = box
        try:
            render_identity = (render_path.stat().st_mtime_ns, render_path.stat().st_size)
        except OSError:
            return ""
        cache_key = (source_id, int(rx1), int(ry1), int(rx2), int(ry2), render_identity)
        with _table_semantic_ocr_cache_lock:
            cached = _table_semantic_ocr_cache.get(cache_key)
        if cached is not None:
            return cached
        image = cached_render_image(render_path)
        if image is None:
            return ""
        height, width = image.shape[:2]
        crop = image[max(0, int(ry1)):min(height, int(ry2)), max(0, int(rx1)):min(width, int(rx2))]
        if crop.size == 0:
            return ""
        text = ""
        try:
            ok, encoded = cv2.imencode(".png", crop)
            if ok:
                completed = subprocess.run(
                    ["tesseract", "stdin", "stdout", "--psm", "6"],
                    input=encoded.tobytes(), capture_output=True, check=False, timeout=20,
                )
                text = completed.stdout.decode("utf-8", errors="ignore")
        except (OSError, subprocess.SubprocessError, ValueError):
            return ""
        with _table_semantic_ocr_cache_lock:
            _table_semantic_ocr_cache[cache_key] = text
            while len(_table_semantic_ocr_cache) > 256:
                _table_semantic_ocr_cache.pop(next(iter(_table_semantic_ocr_cache)))
        return text
    @app.post("/api/table-panel-definitions")
    def table_panel_definitions_save_api():
        payload = json_body(request)
        definitions = payload.get("definitions")
        if not isinstance(definitions, list):
            return jsonify({"error": "definitions moet een lijst zijn"}), 400
        try:
            profile = save_panel_definitions(workspace_root(), definitions=definitions)
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "ok": True,
            "profile": profile,
            "message": f"{len(profile.get('definitions') or [])} tabeldefinitie(s) opgeslagen. Stap 2 gebruikt deze namen voortaan automatisch.",
        })

    @app.post("/api/table-panels")
    def table_panels_save_api():
        payload = json_body(request)
        panels = payload.get("panels")
        if not isinstance(panels, list):
            return jsonify({"error": "panels moet een lijst zijn"}), 400
        try:
            profile = save_panel_profile(
                workspace_root(), panels=panels,
                reference_source_id=str(payload.get("reference_source_id") or "")[:180],
                reference_width=int(payload.get("reference_width") or 0),
                reference_height=int(payload.get("reference_height") or 0),
                mode="manual",
            )
        except (TypeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400
        # A changed panel profile invalidates the previous table/cell measurement.
        # We deliberately preserve the old data for inspection, but the normal
        # workflow will require Step 4 to be rerun before review can continue.
        return jsonify({
            "ok": True, "profile": profile,
            "message": f"{len(profile.get('panels') or [])} fallback-panel(en) opgeslagen. Voer Stap 4 opnieuw uit.",
        })

    @app.post("/api/table-region-ground-truth")
    def table_region_ground_truth_save_api():
        payload = json_body(request)
        source_id = str(payload.get("source_id") or "").strip()
        regions = payload.get("regions")
        if not source_id or not isinstance(regions, list):
            return jsonify({"error": "source_id en regions zijn verplicht"}), 400
        try:
            source = save_table_regions(
                workspace_root(), source_id,
                image_width=int(payload.get("image_width") or 0),
                image_height=int(payload.get("image_height") or 0),
                regions=regions,
                allow_empty=bool(payload.get("allow_empty")),
            )
        except (TypeError, ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({
            "ok": True,
            "source": source,
            "message": f"{len(source.get('regions') or [])} tabelregio('s) opgeslagen als GT voor deze lezing.",
        })

    @app.post("/api/table-region-review/<source_id>")
    def table_region_review_accept_api(source_id: str):
        payload = json_body(request)
        if not _SOURCE_ID_RE.fullmatch(source_id):
            return jsonify({"error": "Ongeldig source_id"}), 400
        source = database.get_detection_source(source_id)
        if source is None:
            return jsonify({"error": "Bron niet gevonden"}), 404
        regions = payload.get("regions")
        if not isinstance(regions, list):
            return jsonify({"error": "regions is verplicht"}), 400
        try:
            saved = save_table_regions(
                workspace_root(), source_id,
                image_width=int(payload.get("image_width") or source.get("image_width") or 0),
                image_height=int(payload.get("image_height") or source.get("image_height") or 0),
                regions=regions,
                allow_empty=bool(payload.get("allow_empty")),
            )
        except (StopIteration, TypeError, ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "source": saved, "message": f"{len(saved.get('regions') or [])} regio’s als nieuwe GT opgeslagen."})

    @app.post("/api/table-region-clear")
    def table_region_clear_api():
        source_id = str(json_body(request).get("source_id") or "").strip()
        if not source_id:
            return jsonify({"error": "source_id is verplicht"}), 400
        removed = clear_table_regions(workspace_root(), source_id)
        return jsonify({
            "ok": True,
            "removed": removed,
            "message": "Tabelregio-GT gewist; er is geen nieuwe detectie gestart.",
        })

    @app.post("/api/table-region-dataset")
    def table_region_dataset_build_api():
        try:
            manifest = build_table_region_dataset(workspace_root())
        except (TypeError, ValueError, OSError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"ok": True, "manifest": manifest, "message": "Tabelregio-dataset opgebouwd."})

    @app.delete("/api/table-panels")
    def table_panels_reset_api():
        try:
            profile = clear_panel_geometry(workspace_root())
        except OSError as exc:
            return jsonify({"error": str(exc)}), 500
        return jsonify({
            "ok": True,
            "profile": profile,
            "message": "Panelkaders verwijderd. De panelnamen uit Stap 1 zijn bewaard.",
        })

    @app.post("/api/table-semantics/<table_id>")
    def table_semantics_save_api(table_id: str):
        payload = json_body(request)
        table_name = str(payload.get("table_name") or "").strip()
        if not table_name:
            return jsonify({"error": "Tabelnaam is verplicht"}), 400
        assignment = save_table_semantic_assignment(workspace_root(), table_id, table_name)
        return jsonify({"ok": True, "table_id": table_id, "assignment": assignment})

    @app.post("/api/table-semantic-detect/<source_id>")
    def table_semantic_detect_api(source_id: str):
        geometry = database.list_detection_table_geometry(source_id)
        profile = load_panel_profile(workspace_root())
        definitions = list(profile.get("definitions") or [])
        relations = database.list_detected_relations(source_id)
        if not definitions:
            return jsonify({"error": "Maak eerst minimaal één tabeldefinitie met sleutelwoorden."}), 400
        regions = list(geometry.get("regions") or [])
        region_boxes = [
            tuple(float(region.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
            for region in regions
        ]
        text_parts_by_region: list[list[str]] = [[] for _ in regions]
        for index, (rx1, ry1, rx2, ry2) in enumerate(region_boxes):
            for relation in relations:
                cx = (float(relation.get("label_x1") or 0) + float(relation.get("label_x2") or 0)) / 2
                cy = (float(relation.get("label_y1") or 0) + float(relation.get("label_y2") or 0)) / 2
                if rx1 <= cx <= rx2 and ry1 <= cy <= ry2:
                    text_parts_by_region[index].extend(
                        str(relation.get(key) or "") for key in ("context_text", "label_text", "header_text", "column_header")
                    )

        # Table-first detection intentionally skips full-page OCR. Run a
        # focused OCR pass on just the regions with no persisted relation
        # context available for semantic assignment - this used to run
        # sequentially, once per such region, each a blocking tesseract
        # subprocess call directly in this request's thread. get_detection_source()
        # does not depend on the region, so it is looked up once here instead
        # of once per region too.
        pending_ocr_indexes = [index for index, parts in enumerate(text_parts_by_region) if not parts]
        if pending_ocr_indexes:
            source = database.get_detection_source(source_id) or {}
            render_path = safe_workspace_file(str(source.get("render_path") or ""))
            if render_path.is_file():
                with ThreadPoolExecutor(max_workers=min(4, len(pending_ocr_indexes))) as pool:
                    future_to_index = {
                        pool.submit(_ocr_text_for_region, render_path, source_id, region_boxes[index]): index
                        for index in pending_ocr_indexes
                    }
                    for future, index in future_to_index.items():
                        text = future.result()
                        if text:
                            text_parts_by_region[index].append(text)

        proposals = []
        for index, region in enumerate(regions):
            text_parts = text_parts_by_region[index]
            haystack = normalize_for_matching(" ".join(text_parts))
            scored = []
            for definition in definitions:
                terms = [str(definition.get("name") or "")] + [str(item) for item in (definition.get("hits") or [])]
                score = sum(1 for term in terms if term and normalize_for_matching(term) in haystack)
                scored.append((score, definition))
            scored.sort(key=lambda item: item[0], reverse=True)
            best_score = scored[0][0] if scored else 0
            tied = [item for item in scored if item[0] == best_score and best_score > 0]
            proposals.append({
                "region_index": index, "table_name": tied[0][1]["name"] if len(tied) == 1 else "",
                "confidence": "matched" if len(tied) == 1 and best_score > 0 else "uncertain",
                "score": best_score, "ocr_text": " | ".join(dict.fromkeys(text_parts))[:1000],
            })
        return jsonify({"ok": True, "source_id": source_id, "proposals": proposals})
