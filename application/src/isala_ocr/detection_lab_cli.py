"""TEMPORARY CLI for the Detectie-lab cell-merging regression investigation.

Runs the three candidate cell-detection approaches for one already-rendered
source and writes overlays + a comparable metrics JSON to the shared training
workspace. This is the job-worker counterpart of
``training.routes_detection_lab``: that route lives in the ``labeler``
container, which deliberately does not install PaddleOCR/PaddlePaddle (see
``infrastructure/docker/Dockerfile.labeler``), so it cannot run
``PPStructureTableEngine`` itself. Instead it enqueues action "62" through the
existing job queue; ``webui-worker.ps1`` picks that up and runs this module
inside the ``training-collector`` container, which does have the full
PaddleOCR/PaddleX stack installed.

Remove this module, ``training/routes_detection_lab.py``, the "62" action
wiring (``webui.py``, ``routes_jobs.py`` options, ``preflight.ps1``,
``webui-worker.ps1``, ``training-menu.ps1``,
``automation/powershell/detection-lab-compare.ps1``) and the sidebar link in
``base.html`` once the regression is understood and one approach has been
folded into the real pipeline.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config
from .logging_utils import configure_logging
from .ocr.table_structure import PPStructureTableEngine, draw_cell_overlay, score_table_structure
from .training.collector import _table_settings_with_active_model, _table_settings_with_active_region_model
from .training.projects import resolve_project_workspace

LOGGER = logging.getLogger(__name__)

_SOURCE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
# Keep this tuple, and the labels below, in sync with training/routes_detection_lab.py
# and templates/detection_lab.html - all three list the same three approaches.
_APPROACHES = ("forced_benchmark", "region_variant_trial", "contrast_lines", "current_default", "hybrid", "hybrid_per_region")
_APPROACH_LABELS = {
    "forced_benchmark": "Probeer 1 · Volledige benchmark (regio-model genegeerd)",
    "region_variant_trial": "Probeer 2 · Regio-model + variant-trial per regio",
    "contrast_lines": "Probeer 3 · Contrastlijnen tussen rijen",
    "current_default": "Probeer 4 · Huidige standaarddetectie",
    "hybrid": "Probeer 5 · Hybride Stap 1 + Stap 2",
    "hybrid_per_region": "Probeer 6 · Hybride per tabelregio",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isala_ocr.detection_lab_cli",
        description="Run the three Detectie-lab cell-detection approaches for one source.",
    )
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--source-id", required=True)
    run.add_argument("--workspace", default="/training/workspace")
    run.add_argument("--table-model-id", default="active")
    run.add_argument("--config", default="/app/config/app.yaml")
    return parser


def _table_settings(workspace: Path, config: Any) -> dict[str, Any]:
    raw = dict(config.raw.get("training", {}).get("collection", {}).get("table_structure", {}) or {})
    return _table_settings_with_active_region_model(workspace, raw)


def _run(args: argparse.Namespace) -> int:
    import cv2

    source_id = str(args.source_id or "").strip()
    if not _SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError(f"Ongeldig source_id: {source_id!r}")

    config = load_config(args.config)
    workspace = resolve_project_workspace(args.workspace)
    render_path = workspace / "source_renders" / f"{source_id}.png"
    if not render_path.is_file():
        raise RuntimeError(
            f"Geen bronrender gevonden: {render_path}. Draai eerst Stap 4/5 voor deze bron."
        )
    image = cv2.imread(str(render_path))
    if image is None:
        raise RuntimeError(f"Bronrender kon niet worden gelezen: {render_path}")

    out_dir = workspace / "detection_lab"
    out_dir.mkdir(parents=True, exist_ok=True)

    settings, _ = _table_settings_with_active_model(workspace, _table_settings(workspace, config), args.table_model_id)
    engine = PPStructureTableEngine(config.ocr, settings)
    engine.warmup()

    run_token = int(time.time() * 1000)
    results: dict[str, Any] = {}
    detected_regions: dict[str, Any] = {}
    for approach in _APPROACHES:
        LOGGER.info("Draai aanpak %s voor bron %s", approach, source_id)
        try:
            if approach == "forced_benchmark":
                regions, diagnostics = engine.detect_with_forced_full_benchmark(image, source_id=source_id)
            elif approach == "region_variant_trial":
                regions, diagnostics = engine.detect_with_trained_regions_benchmark(image, source_id=source_id)
            elif approach == "contrast_lines":
                regions, diagnostics = engine.detect_with_contrast_lines(image, source_id=source_id)
            elif approach == "current_default":
                regions, diagnostics = engine.detect_with_benchmark(image, source_id=source_id)
            elif approach in ("hybrid", "hybrid_per_region"):
                regions, diagnostics = engine.detect_with_hybrid_benchmark(
                    image, source_id=source_id,
                    base_regions=detected_regions.get("forced_benchmark"),
                    alternate_regions=detected_regions.get("region_variant_trial"),
                    allow_cross_column=approach == "hybrid_per_region",
                )
            else:
                regions, diagnostics = engine.detect_with_benchmark(image, source_id=source_id)
            detected_regions[approach] = regions
            metrics = score_table_structure(regions)
            overlay = draw_cell_overlay(image, regions)
            if approach == "contrast_lines":
                # Keep the separator evidence visible in the comparison image;
                # otherwise the result only shows the downstream cell boxes and
                # the reviewer cannot tell where Probeer 3 intervened.
                scan_boxes = diagnostics.get("scan_boxes") or [diagnostics.get("panel_box")]
                for y in diagnostics.get("line_positions", []):
                    for scan_box in scan_boxes:
                        if not scan_box:
                            continue
                        x1, y1, x2, y2 = [int(value) for value in scan_box]
                        if y1 < int(y) < y2:
                            cv2.line(overlay, (x1, int(y)), (x2, int(y)), (255, 0, 255), 2, cv2.LINE_AA)
            filename = f"{source_id}-{approach}-{run_token}.png"
            if not cv2.imwrite(str(out_dir / filename), overlay):
                raise RuntimeError("Overlay kon niet worden opgeslagen")
            results[approach] = {
                "ok": True,
                "label": _APPROACH_LABELS[approach],
                "image_file": filename,
                "metrics": metrics,
                "diagnostics": {
                    key: value for key, value in diagnostics.items() if key not in ("runs", "regions")
                },
            }
        except Exception as exc:  # noqa: BLE001 - report per approach, keep comparing the rest
            # One approach failing (e.g. a missing model) must not stop the
            # other two from producing a result: that comparison is the whole
            # point of this tool.
            LOGGER.exception("Aanpak %s mislukt voor bron %s", approach, source_id)
            results[approach] = {
                "ok": False,
                "label": _APPROACH_LABELS.get(approach, approach),
                "error": f"{type(exc).__name__}: {exc}",
            }

    payload = {"source_id": source_id, "generated_at": run_token, "results": results}
    results_path = out_dir / f"{source_id}-results.json"
    temp = results_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(results_path)
    print(json.dumps({"ok": True, "source_id": source_id, "results_file": results_path.name}, ensure_ascii=False), flush=True)
    return 0 if any(bool(item.get("ok")) for item in results.values()) else 1


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(arguments)
    configure_logging(args.log_level)
    try:
        if args.command == "run":
            return _run(args)
        parser.error(f"Unsupported command: {args.command}")
        return 2
    except (ConfigError, FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
