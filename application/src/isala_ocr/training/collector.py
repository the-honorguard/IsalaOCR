from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import cv2
import numpy as np

from ..config import AppConfig
from ..geometry import scale_box
from ..image_io import load_input
from ..models import Box
from ..study_info import extract_study_info
from ..ocr.table_structure import PPStructureTableEngine, TABLE_ENGINE_VERSION
from ..ocr.base import OCREngine
from .projects import resolve_project_workspace
from .db import TrainingDatabase, utc_now
from .dynamic_locator import LOCATOR_VERSION, LocatedField, locate_fields
from .header_normalization import load_header_aliases
from .generic_detection import GENERIC_DETECTOR_VERSION, detect_generic_structure, integrate_table_regions
from .localization import (
    LOCALIZATION_CANDIDATE_VERSION, fuse_candidates, table_cell_candidates,
    text_geometry_candidates, write_candidate_crops,
)
from .mapping import ensure_default_field_definitions, suggest_mappings
from .table_quality import table_first_quality
from .table_panels import load_panel_profile, panel_boxes_for_image
from .table_cell_training import active_table_cell_model, list_table_cell_models

LOGGER = logging.getLogger(__name__)


def _table_settings_with_active_model(root: Path, settings: dict, selected_model_id: str | None = None) -> tuple[dict, dict | None]:
    result = dict(settings)
    requested = str(selected_model_id or "").strip()
    if requested in {"", "active"}:
        selected = active_table_cell_model(root)
    elif requested in {"generic-ppstructure", "baseline"}:
        selected = None
    else:
        selected = next((item for item in list_table_cell_models(root) if str(item.get("model_id") or "") == requested), None)
        if selected:
            inference_dir = root / str(selected.get("inference_dir") or "")
            if not inference_dir.is_dir():
                selected = None
            else:
                selected = {**selected, "inference_path": str(inference_dir)}
        if selected is None:
            raise ValueError(f"Onbekend of ongeldig table-cell model: {requested}")
    if selected:
        result["wireless_cells_model"] = str(selected.get("model_name") or "RT-DETR-L_wireless_table_cell_det")
        result["wireless_cells_model_dir"] = str(selected["inference_path"])
        LOGGER.info("Using selected project table-cell model: %s", selected.get("model_id"))
    return result, selected


def _table_settings_with_active_region_model(root: Path, settings: dict) -> dict:
    result = dict(settings)
    pointer = root / "table_region_models" / "active.json"
    if not pointer.is_file():
        return result
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8-sig"))
        inference_dir = root / str(payload.get("inference_dir") or "")
    except (OSError, TypeError, ValueError):
        return result
    if inference_dir.is_dir():
        result["table_region_model_dir"] = str(inference_dir)
        LOGGER.info("Using active full-page table-region model: %s", payload.get("model_id"))
    return result


def _files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(path)
    ignored_suffixes = {".ini", ".yaml", ".yml", ".json", ".txt", ".log"}
    return sorted(
        item
        for item in path.rglob("*")
        if item.is_file()
        and not any(part.startswith(".") for part in item.relative_to(path).parts)
        and item.suffix.lower() not in ignored_suffixes
    )


def _joined(tokens) -> tuple[str, float]:
    nonempty = [token for token in tokens if token.text != ""]
    if not nonempty:
        return "", 0.0
    # Recognition-only normally returns one token. Preserve that text exactly;
    # joining is only a fallback for engines that return multiple fragments.
    text = nonempty[0].text if len(nonempty) == 1 else " ".join(token.text for token in nonempty)
    weights = [max(len(token.text), 1) for token in nonempty]
    confidence = sum(
        token.confidence * max(len(token.text), 1) for token in nonempty
    ) / sum(weights)
    return text, float(confidence)


def _crop_hash(crop: np.ndarray) -> str:
    digest = hashlib.sha256()
    digest.update(str(crop.shape).encode("ascii"))
    digest.update(str(crop.dtype).encode("ascii"))
    digest.update(np.ascontiguousarray(crop).tobytes())
    return digest.hexdigest()


def _fixed_locations(
    config: AppConfig,
    width: int,
    height: int,
    padding: int,
) -> list[LocatedField]:
    result: list[LocatedField] = []
    for field in config.profile.fields:
        box = scale_box(
            field.roi,
            config.profile.reference_width,
            config.profile.reference_height,
            width,
            height,
        ).padded(padding).clamp(width, height)
        result.append(
            LocatedField(
                field=field,
                box=box,
                method="fixed_roi",
                locator_confidence=0.0,
                matched_label="",
                matched_label_box=None,
                panel=field.panel,
            )
        )
    return result


def _write_locator_overlay(
    destination: Path,
    image: np.ndarray,
    locations: list[LocatedField],
) -> None:
    if image.ndim == 2:
        overlay = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 1:
        overlay = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        overlay = image[:, :, :3].copy()
    for item in locations:
        box = item.box
        if item.method == "fixed_fallback":
            color = (0, 0, 255)
        elif item.method == "dynamic_row_band":
            color = (0, 200, 255)
        else:
            color = (0, 200, 0)
        cv2.rectangle(overlay, (box.x1, box.y1), (box.x2, box.y2), color, 1)
        cv2.putText(
            overlay,
            f"{item.field.key} {item.method} {item.locator_confidence:.2f}",
            (box.x1, max(12, box.y1 - 3)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            color,
            1,
            cv2.LINE_AA,
        )
        if item.matched_label_box:
            label = item.matched_label_box
            cv2.rectangle(overlay, (label.x1, label.y1), (label.x2, label.y2), (255, 160, 0), 1)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(destination), overlay):
        raise RuntimeError(f"Could not save locator overlay: {destination}")



def _collect_localization_detections(
    input_path: str | Path,
    workspace: str | Path,
    config: AppConfig,
    locator_engine: OCREngine,
    table_model_id: str | None = None,
) -> dict[str, object]:
    """Pipeline A: detect crop geometry only.

    Recognition text is never persisted here. OCR is used only as a geometry
    provider, while PP-Structure contributes table/cell geometry. Functional
    labels, mapping relations and raw values are deliberately deferred to
    Pipeline B.
    """
    root = resolve_project_workspace(workspace)
    source_renders_root = root / "source_renders"
    diagnostics_root = root / "localization_detections"
    source_renders_root.mkdir(parents=True, exist_ok=True)
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    database = TrainingDatabase(root / "samples.sqlite3")
    sources = _files(Path(input_path))
    # One immutable identity for this complete Step-3 pass.  It is persisted in
    # every per-source diagnostic so later model activation can never relabel
    # stale predictions as if they were produced by the newly active model.
    detection_started_at = utc_now()
    detection_batch_id = "step3-" + hashlib.sha256(
        (detection_started_at + "|" + str(len(sources))).encode("utf-8")
    ).hexdigest()[:16]

    table_settings = dict(
        config.raw.get("training", {}).get("collection", {}).get("table_structure", {}) or {}
    )
    table_settings, active_table_model = _table_settings_with_active_model(root, table_settings, table_model_id)
    table_settings = _table_settings_with_active_region_model(root, table_settings)
    selected_table_model = active_table_model
    localization_settings = dict(config.raw.get("training", {}).get("localization", {}) or {})
    strategy = str(localization_settings.get("strategy") or "fusion").strip().lower()
    table_first = strategy == "table_first"
    table_first_settings = dict(localization_settings.get("table_first", {}) or {})
    panel_profile = load_panel_profile(root) if table_first else {"panels": []}
    effective_detector_version = TABLE_ENGINE_VERSION if table_first else LOCALIZATION_CANDIDATE_VERSION
    # A pure table-first geometry pass does not need the separate full-page OCR
    # locator at all. PP-Structure runs its own table/cell pipeline. Keeping the
    # loose OCR detector out of this pass makes both the measurement and runtime
    # cost easier to interpret. Legacy fusion still uses OCR text geometry.
    if not table_first:
        locator_engine.warmup()
    table_engine = None
    table_engine_error = ""
    if bool(table_settings.get("enabled", True)):
        try:
            table_engine = PPStructureTableEngine(config.ocr, table_settings)
            table_engine.warmup()
        except Exception as exc:
            table_engine_error = f"{type(exc).__name__}: {exc}"
            if table_first:
                LOGGER.exception("PP-StructureV3 unavailable in table-first mode")
                raise RuntimeError(
                    "Table-first localization requires PP-StructureV3. Open Stap 1 · Voorbereiding "
                    "and install/check the inference OCR + table models before running Stap 2."
                ) from exc
            LOGGER.exception("PP-StructureV3 unavailable; continuing with text geometry only")
            if not bool(table_settings.get("fail_open", True)):
                raise

    detected_sources = 0
    failed_sources = 0
    total_candidates = 0
    total_tables = 0
    total_cells = 0
    for source_index, source in enumerate(sources, start=1):
        try:
            decoded = load_input(source, config.dicom)
            height, width = decoded.image.shape[:2]
            if table_first:
                tokens = []
            else:
                batches = locator_engine.recognize_many([decoded.image])
                if len(batches) != 1:
                    raise RuntimeError("Full-page OCR did not return one result for one source image")
                tokens = batches[0]
            table_regions = []
            table_preprocessing: dict[str, object] = {"enabled": False}
            if table_engine is not None:
                try:
                    if table_first and bool(table_first_settings.get("preprocessing_benchmark", True)):
                        learned_region_model = str(table_settings.get("table_region_model_dir") or "").strip()
                        manual_panels = panel_boxes_for_image(panel_profile, width, height)
                        if learned_region_model:
                            table_regions, table_preprocessing = table_engine.detect_with_benchmark(
                                decoded.image, source_id=decoded.source_id, fallback_tokens=tokens
                            )
                            table_preprocessing["table_region_model"] = learned_region_model
                        elif manual_panels:
                            table_regions, table_preprocessing = table_engine.detect_panels_with_benchmark(
                                decoded.image, source_id=decoded.source_id, panels=manual_panels
                            )
                            table_preprocessing["panel_profile_updated_at"] = str(panel_profile.get("updated_at") or "")
                        else:
                            # Bootstrap pass: generate a full-image render and table suggestions so
                            # the user can draw authoritative panels in Panel Setup. This output is
                            # intentionally marked as provisional and should be rerun after panels are saved.
                            table_regions, table_preprocessing = table_engine.detect_with_benchmark(
                                decoded.image, source_id=decoded.source_id, fallback_tokens=tokens
                            )
                            table_preprocessing["panel_setup_required"] = True
                            table_preprocessing["panel_mode"] = "bootstrap_suggestion"
                    else:
                        table_regions = table_engine.detect(
                            decoded.image, source_id=decoded.source_id, fallback_tokens=tokens
                        )
                except Exception:
                    LOGGER.exception("Table geometry failed for input item %d", source_index)
                    if table_first or not bool(table_settings.get("fail_open", True)):
                        raise

            cell_candidates = table_cell_candidates(
                decoded.source_id, table_regions, image_width=width, image_height=height,
                include_broad_cells=table_first or bool(table_first_settings.get("include_broad_cells", False)),
            )
            if table_first:
                # Table-first experiment: cell geometry is authoritative. Do not
                # blend OCR text boxes into the candidate pool and do not NMS table
                # cells against each other; neighbouring/merged cells may overlap by
                # a few pixels and are still distinct structural objects.
                candidates = list(cell_candidates)
                text_candidate_count = 0
            else:
                text_candidates = text_geometry_candidates(
                    decoded.source_id, tokens, image_width=width, image_height=height,
                    padding=int(localization_settings.get("text_padding", 2)),
                )
                candidates = fuse_candidates(
                    decoded.source_id,
                    [*text_candidates, *cell_candidates],
                    iou_threshold=float(localization_settings.get("fusion_iou", 0.55)),
                    containment_threshold=float(localization_settings.get("fusion_containment", 0.92)),
                )
                text_candidate_count = len(text_candidates)

            render_relative = Path("source_renders") / f"{decoded.source_id}.png"
            render_path = root / render_relative
            if not cv2.imwrite(str(render_path), decoded.image):
                raise RuntimeError(f"Could not save local source render: {render_path}")
            crop_paths = write_candidate_crops(root, decoded.source_id, decoded.image, candidates)
            candidate_payloads: list[dict[str, object]] = []
            for candidate in candidates:
                payload = candidate.as_dict()
                payload["crop_path"] = crop_paths.get(candidate.candidate_id, "")
                candidate_payloads.append(payload)
            table_payloads = [table.as_dict() for table in table_regions]
            database.replace_localization_detection(
                {
                    "source_id": decoded.source_id,
                    "image_width": width,
                    "image_height": height,
                    "render_path": render_relative.as_posix(),
                    "detector_version": effective_detector_version,
                    "token_count": len(tokens),
                },
                candidate_payloads,
                table_payloads,
            )
            # Do not write OCR text to Pipeline A diagnostics. The only persisted
            # content is geometry, source provenance and confidence.
            diagnostic = {
                "schema_version": "3.1-localization-run-aware",
                "source_id": decoded.source_id,
                "detection_batch_id": detection_batch_id,
                "detected_at": detection_started_at,
                "image_width": width,
                "image_height": height,
                "detector_version": effective_detector_version,
                "strategy": strategy,
                "candidate_count": len(candidate_payloads),
                "text_candidate_count": text_candidate_count,
                "table_count": len(table_payloads),
                "table_cell_count": sum(len(item.get("cells") or []) for item in table_payloads),
                "preprocessing_benchmark": table_preprocessing,
                "active_table_cell_model": ({
                    "model_id": str(selected_table_model.get("model_id") or "generic-ppstructure"),
                    "model_name": str(selected_table_model.get("model_name") or "Generieke PP-Structure wireless table-cell detector"),
                    "run_id": str(selected_table_model.get("run_id") or ""),
                    "dataset_id": str(selected_table_model.get("dataset_id") or ""),
                    "activated_at": str(selected_table_model.get("activated_at") or ""),
                    "selection": "explicit" if table_model_id else "active-default",
                } if selected_table_model else {
                    "model_id": "generic-ppstructure",
                    "model_name": "Generieke PP-Structure wireless table-cell detector",
                    "run_id": "",
                    "dataset_id": "",
                    "activated_at": "",
                    "selection": "explicit" if table_model_id else "generic-default",
                }),
                "panel_profile": ({
                    "mode": str(panel_profile.get("mode") or "manual"),
                    "updated_at": str(panel_profile.get("updated_at") or ""),
                    "panel_count": len(panel_profile.get("panels") or []),
                    "panels": list(panel_profile.get("panels") or []),
                } if table_first else {}),
                "candidates": candidate_payloads,
                "tables": [
                    {
                        "table_id": table["table_id"], "confidence": table.get("confidence", 0),
                        "x1": table["x1"], "y1": table["y1"], "x2": table["x2"], "y2": table["y2"],
                        "cells": [
                            {k: cell[k] for k in ("cell_id","row_index","column_index","confidence","x1","y1","x2","y2")}
                            for cell in (table.get("cells") or [])
                        ],
                    }
                    for table in table_payloads
                ],
            }
            (diagnostics_root / f"{decoded.source_id}.json").write_text(
                json.dumps(diagnostic, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            detected_sources += 1
            total_candidates += len(candidate_payloads)
            total_tables += len(table_payloads)
            total_cells += sum(len(item.get("cells") or []) for item in table_payloads)
        except Exception:
            failed_sources += 1
            LOGGER.exception("Could not perform localization detection for input item %d", source_index)

    manifest = {
        "created_at": utc_now(),
        "detection_batch_id": detection_batch_id,
        "detection_started_at": detection_started_at,
        "flow": "table_first_localization" if table_first else "field_localization",
        "strategy": strategy,
        "detector_version": effective_detector_version,
        "input_items": len(sources),
        "detected_sources": detected_sources,
        "failed_items": failed_sources,
        "candidate_count": total_candidates,
        "table_count": total_tables,
        "table_cell_count": total_cells,
        "locator_geometry_engine": ({"enabled": False, "reason": "table_first_geometry_only"} if table_first else locator_engine.info()),
        "table_structure_engine": table_engine.info() if table_engine is not None else {"enabled": False, "error": table_engine_error},
        "active_table_cell_model": ({
            "model_id": str(selected_table_model.get("model_id") or "generic-ppstructure"),
            "model_name": str(selected_table_model.get("model_name") or "Generieke PP-Structure wireless table-cell detector"),
            "activated_at": str(selected_table_model.get("activated_at") or ""),
            "selection": "explicit" if table_model_id else "active-default",
        } if selected_table_model else {
            "model_id": "generic-ppstructure",
            "model_name": "Generieke PP-Structure wireless table-cell detector",
            "activated_at": "",
            "selection": "explicit" if table_model_id else "generic-default",
        }),
        "pipeline_boundary": {
            "raw_ocr_persisted": False,
            "field_mapping_created": False,
            "value_recognition_run": False,
            "output_measurements_created": False,
        },
    }
    (root / "localization_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if table_first and failed_sources:
        raise RuntimeError(
            f"Table-first detection failed for {failed_sources} of {len(sources)} source item(s). "
            "Review the per-source log before judging table coverage; partial results are not accepted as a valid experiment."
        )
    if table_first:
        # Step 7 keeps detection runs separate from the canonical Step-4 Ground Truth.
        # Capture only complete Step-3 passes; if no GT dataset exists yet (the first
        # run), the comparison module intentionally does nothing.
        try:
            from .table_model_comparison import capture_current_detection_run
            capture_current_detection_run(root)
        except Exception:
            # Comparison history is secondary metadata. A successful localization
            # run must never be turned into a failed detection run by dashboard
            # bookkeeping; Step 7 can reconstruct/capture it lazily later.
            LOGGER.exception("Could not archive Step-3 table-cell comparison run")
    return manifest


def collect_mapping_detections(
    input_path: str | Path,
    workspace: str | Path,
    config: AppConfig,
    locator_engine: OCREngine,
    recognition_engine: OCREngine,
) -> dict[str, object]:
    """Pipeline B preparation: semantic OCR blocks and mapping relations.

    This function must only be called after the detection quality gate.
    """
    database = TrainingDatabase(resolve_project_workspace(workspace) / "samples.sqlite3")
    localization_settings = dict(config.raw.get("training", {}).get("localization", {}) or {})
    strategy = str(localization_settings.get("strategy") or "fusion").strip().lower()
    if strategy == "table_first":
        table_settings = dict(localization_settings.get("table_first", {}) or {})
        gate = table_first_quality(
            database,
            minimum_direct_coverage=float(table_settings.get("minimum_direct_coverage", 0.95)),
            maximum_false_candidate_rate=float(table_settings.get("maximum_false_candidate_rate", 0.10)),
            maximum_adjustment_rate=float(table_settings.get("maximum_adjustment_rate", 0.25)),
        )
        if not gate.get("ready"):
            raise RuntimeError(
                f"TABLE-FIRST CHECK is closed: {gate.get('reason') or 'table geometry is not approved'}. "
                f"Next step: {gate.get('next_step') or 'review table cells'}"
            )
    else:
        gate = database.detection_gate()
        if not gate.get("ready"):
            raise RuntimeError(f"Detection gate is closed: {gate.get('reason') or 'localization is not approved'}")
    return _collect_mapping_detections(input_path, workspace, config, locator_engine, recognition_engine)


def _collect_mapping_detections(
    input_path: str | Path,
    workspace: str | Path,
    config: AppConfig,
    locator_engine: OCREngine,
    recognition_engine: OCREngine,
) -> dict[str, object]:
    root = resolve_project_workspace(workspace)
    diagnostics_root = root / "generic_detections"
    blocks_root = root / "detected_blocks"
    source_renders_root = root / "source_renders"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    blocks_root.mkdir(parents=True, exist_ok=True)
    source_renders_root.mkdir(parents=True, exist_ok=True)
    database = TrainingDatabase(root / "samples.sqlite3")
    ensure_default_field_definitions(database, config.profile)
    sources = _files(Path(input_path))
    locator_engine.warmup()
    table_settings = dict(
        config.raw.get("training", {}).get("collection", {}).get("table_structure", {}) or {}
    )
    table_settings, active_table_model = _table_settings_with_active_model(root, table_settings)
    table_engine = None
    table_engine_error = ""
    if bool(table_settings.get("enabled", True)):
        try:
            table_engine = PPStructureTableEngine(config.ocr, table_settings)
            table_engine.warmup()
        except Exception as exc:
            table_engine_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("PP-StructureV3 table pipeline is unavailable; continuing with generic OCR relations")
            if not bool(table_settings.get("fail_open", True)):
                raise
    detected_sources = 0
    failed_sources = 0
    total_blocks = 0
    total_relations = 0
    total_suggestions = 0

    for source_index, source in enumerate(sources, start=1):
        try:
            decoded = load_input(source, config.dicom)
            height, width = decoded.image.shape[:2]
            batches = locator_engine.recognize_many([decoded.image])
            if len(batches) != 1:
                raise RuntimeError("Generic detector did not return one OCR result for one source")
            tokens = batches[0]
            blocks, relations, detector_diagnostics = detect_generic_structure(
                decoded.source_id, decoded.image.shape, tokens
            )
            table_regions = []
            table_diagnostics = {
                "enabled": bool(table_engine is not None),
                "engine_version": TABLE_ENGINE_VERSION,
                "table_count": 0,
                "table_cell_count": 0,
                "table_relation_count": 0,
                "generic_relations_replaced": 0,
                "error": table_engine_error,
            }
            if table_engine is not None:
                try:
                    table_regions = table_engine.detect(
                        decoded.image, source_id=decoded.source_id, fallback_tokens=tokens
                    )
                    blocks, relations, structural = integrate_table_regions(
                        decoded.source_id, blocks, relations, table_regions
                    )
                    table_diagnostics.update(structural)
                except Exception as exc:
                    table_diagnostics["error"] = f"{type(exc).__name__}: {exc}"
                    LOGGER.exception("Table structure recognition failed for input item %d", source_index)
                    if not bool(table_settings.get("fail_open", True)):
                        raise
            detector_diagnostics["table_structure"] = table_diagnostics
            detector_diagnostics["block_count"] = len(blocks)
            detector_diagnostics["relation_count"] = len(relations)
            render_relative = Path("source_renders") / f"{decoded.source_id}.png"
            render_path = root / render_relative
            if not cv2.imwrite(str(render_path), decoded.image):
                raise RuntimeError(f"Could not save local source render: {render_path}")

            source_block_dir = blocks_root / decoded.source_id
            source_block_dir.mkdir(parents=True, exist_ok=True)
            block_payloads: list[dict[str, object]] = []
            for block in blocks:
                payload = block.as_dict()
                box = block.box.clamp(width, height)
                crop = decoded.image[box.y1:box.y2, box.x1:box.x2]
                relative = ""
                if crop.size:
                    destination = source_block_dir / f"{block.block_id}.png"
                    if cv2.imwrite(str(destination), crop):
                        relative = destination.relative_to(root).as_posix()
                payload["crop_path"] = relative
                block_payloads.append(payload)
            relation_payloads = [relation.as_dict() for relation in relations]
            database.replace_generic_detection(
                {
                    "source_id": decoded.source_id,
                    "image_width": width,
                    "image_height": height,
                    "render_path": render_relative.as_posix(),
                    "detector_version": GENERIC_DETECTOR_VERSION,
                    "token_count": detector_diagnostics.get("ocr_token_count", 0),
                },
                block_payloads,
                relation_payloads,
            )
            suggestions = suggest_mappings(database, decoded.source_id)
            study_info = extract_study_info(tokens)
            payload = {
                "schema_version": "2.0",
                "source_id": decoded.source_id,
                "detector": detector_diagnostics,
                "study_info": study_info.as_dict(),
                "blocks": block_payloads,
                "relations": relation_payloads,
                "tables": [table.as_dict() for table in table_regions],
                "automatic_mapping_suggestions": len(suggestions),
            }
            (diagnostics_root / f"{decoded.source_id}.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            detected_sources += 1
            total_blocks += len(blocks)
            total_relations += len(relations)
            total_suggestions += len(suggestions)
        except Exception:
            failed_sources += 1
            LOGGER.exception("Could not perform generic detection for input item %d", source_index)

    manifest = {
        "created_at": utc_now(),
        "flow": "generic_mapping",
        "detector_version": GENERIC_DETECTOR_VERSION,
        "input_items": len(sources),
        "detected_sources": detected_sources,
        "failed_items": failed_sources,
        "detected_blocks": total_blocks,
        "proposed_relations": total_relations,
        "automatic_mapping_suggestions": total_suggestions,
        "locator_engine": locator_engine.info(),
        "table_structure_engine": table_engine.info() if table_engine is not None else {"enabled": False, "error": table_engine_error},
        "recognition_engine_reserved_for_mapping_stage": recognition_engine.info(),
        "diagnostics": {
            "json_directory": "generic_detections",
            "block_crop_directory": "detected_blocks",
            "source_render_directory": "source_renders",
        },
        "privacy": {
            "source_filenames_stored": False,
            "dicom_identifiers_stored": False,
            "source_id": "first 24 hexadecimal characters of SHA-256 over source bytes",
        },
    }
    (root / "collection_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest

def collect_samples(
    input_path: str | Path,
    workspace: str | Path,
    config: AppConfig,
    engine: OCREngine,
    padding_pixels: int | None = None,
    locator_engine: OCREngine | None = None,
    locator_mode: str | None = None,
    table_model_id: str | None = None,
) -> dict[str, object]:
    flow = str(
        config.raw.get("training", {}).get("collection", {}).get("flow", "legacy_profile")
    ).strip().lower()
    if flow == "generic_mapping":
        if locator_engine is None:
            raise ValueError("Generic detection requires a full-page locator OCR engine")
        return _collect_localization_detections(input_path, workspace, config, locator_engine, table_model_id)

    root = resolve_project_workspace(workspace)
    crop_root = root / "crops" / "original"
    diagnostics_root = root / "collection_diagnostics"
    overlays_root = root / "locator_overlays"
    source_renders_root = root / "source_renders"
    header_crops_root = root / "header_crops"
    extracted_output_root = root / "extracted_output"
    crop_root.mkdir(parents=True, exist_ok=True)
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    overlays_root.mkdir(parents=True, exist_ok=True)
    source_renders_root.mkdir(parents=True, exist_ok=True)
    header_crops_root.mkdir(parents=True, exist_ok=True)
    extracted_output_root.mkdir(parents=True, exist_ok=True)
    db = TrainingDatabase(root / "samples.sqlite3")
    sources = _files(Path(input_path))
    added = 0
    refreshed = 0
    failed = 0
    dynamic_count = 0
    fallback_count = 0
    changed_review_count = 0
    field_count = len(config.profile.fields)
    padding = int(
        padding_pixels
        if padding_pixels is not None
        else config.raw.get("training", {}).get("collection", {}).get("padding_pixels", 2)
    )
    dynamic_settings = config.profile.dynamic_extraction
    requested_mode = str(
        locator_mode
        or config.raw.get("training", {}).get("collection", {}).get("locator", "dynamic")
    ).lower()
    dynamic_enabled = bool(dynamic_settings.get("enabled", False)) and requested_mode != "fixed"
    if dynamic_enabled and locator_engine is None:
        raise ValueError("Dynamic collection requires a locator OCR engine")

    header_alias_model_path = root / "header_normalization" / "model.json"
    learned_header_aliases = load_header_aliases(header_alias_model_path, config.profile)

    # Initialize once, before entering the per-DICOM loop. A model/cache error
    # should fail the collection once instead of producing the same traceback
    # for every input item and leaving PaddleX partially initialized.
    if dynamic_enabled and locator_engine is not None:
        locator_engine.warmup()
    engine.warmup()

    for source_index, source in enumerate(sources, start=1):
        try:
            decoded = load_input(source, config.dicom)
            height, width = decoded.image.shape[:2]
            if dynamic_enabled:
                panel_search_x2 = int(round(
                    float(dynamic_settings.get("panel_search_x2", 650))
                    * width / config.profile.reference_width
                ))
                locator_image = decoded.image[:, : min(max(panel_search_x2, 1), width)]
                detected_batches = locator_engine.recognize_many([locator_image])
                if len(detected_batches) != 1:
                    raise RuntimeError("Locator OCR did not return one result for one source image")
                locator_tokens = detected_batches[0]
                locations, locator_diagnostics = locate_fields(
                    decoded.image.shape,
                    locator_tokens,
                    config.profile,
                    padding_pixels=padding,
                    learned_aliases=learned_header_aliases,
                )
                if len(locations) != field_count:
                    raise RuntimeError(
                        f"Dynamic locator returned {len(locations)} fields; expected {field_count}"
                    )
            else:
                locator_tokens = []
                locations = _fixed_locations(config, width, height, padding)
                locator_diagnostics = {
                    "locator_version": "fixed-roi-v1",
                    "detected_tokens": 0,
                    "detected_lines": 0,
                }

            crops: list[np.ndarray] = []
            for location in locations:
                box = location.box
                crop = decoded.image[box.y1 : box.y2, box.x1 : box.x2]
                if crop.size == 0:
                    raise ValueError(f"Empty crop for field {location.field.key}")
                crops.append(crop)
            recognized = engine.recognize_many(crops)
            if len(recognized) != len(crops):
                raise RuntimeError("Recognition result count does not match crop count")

            source_dir = crop_root / decoded.source_id
            source_dir.mkdir(parents=True, exist_ok=True)
            header_source_dir = header_crops_root / decoded.source_id
            header_source_dir.mkdir(parents=True, exist_ok=True)
            study_info = extract_study_info(locator_tokens)
            source_diagnostics: dict[str, object] = {
                **locator_diagnostics,
                "source_id": decoded.source_id,
                "image_width": width,
                "image_height": height,
                "study_info": study_info.as_dict(),
                "fields": [],
            }
            _write_locator_overlay(
                overlays_root / f"{decoded.source_id}.png",
                decoded.image,
                locations,
            )
            # Keep a local rendered source image so the browser can show the full
            # DICOM and draw selectable HTML/SVG overlays without requiring
            # PaddleOCR, pydicom or OpenCV inside the lightweight web container.
            render_path = source_renders_root / f"{decoded.source_id}.png"
            if not cv2.imwrite(str(render_path), decoded.image):
                raise RuntimeError(f"Could not save local source render: {render_path}")

            for location, crop, tokens in zip(locations, crops, recognized, strict=True):
                field = location.field
                box = location.box
                sample_id = f"{decoded.source_id}_{field.key}"
                relative = Path("crops") / "original" / decoded.source_id / f"{field.key}.png"
                destination = root / relative
                crop_sha256 = _crop_hash(crop)
                previous = db.get(sample_id)
                if not cv2.imwrite(str(destination), crop):
                    raise RuntimeError(f"Could not save crop: {destination}")
                raw_text, confidence = _joined(tokens)

                header_relative = ""
                header_sha256 = ""
                label_x1 = label_y1 = label_x2 = label_y2 = -1
                if location.matched_label_box is not None:
                    label_box = location.matched_label_box.padded(3).clamp(width, height)
                    label_x1, label_y1, label_x2, label_y2 = (
                        label_box.x1, label_box.y1, label_box.x2, label_box.y2
                    )
                    header_crop = decoded.image[label_box.y1:label_box.y2, label_box.x1:label_box.x2]
                    if header_crop.size:
                        header_path = header_source_dir / f"{field.key}.png"
                        if not cv2.imwrite(str(header_path), header_crop):
                            raise RuntimeError(f"Could not save header crop: {header_path}")
                        header_relative = (Path("header_crops") / decoded.source_id / f"{field.key}.png").as_posix()
                        header_sha256 = _crop_hash(header_crop)

                inserted = db.upsert_sample(
                    {
                        "sample_id": sample_id,
                        "source_id": decoded.source_id,
                        "profile": config.profile.name,
                        "field_key": field.key,
                        "field_label": field.label,
                        "crop_path": relative.as_posix(),
                        "raw_ocr": raw_text,
                        "raw_confidence": confidence,
                        "raw_variant": f"recognition_only_{location.method}",
                        "image_width": width,
                        "image_height": height,
                        "roi_x1": box.x1,
                        "roi_y1": box.y1,
                        "roi_x2": box.x2,
                        "roi_y2": box.y2,
                        "extraction_method": location.method,
                        "locator_confidence": location.locator_confidence,
                        "locator_label_text": location.matched_label,
                        "locator_version": str(locator_diagnostics.get("locator_version", LOCATOR_VERSION)),
                        "locator_label_x1": label_x1,
                        "locator_label_y1": label_y1,
                        "locator_label_x2": label_x2,
                        "locator_label_y2": label_y2,
                        "header_crop_path": header_relative,
                        "header_crop_sha256": header_sha256,
                        "crop_sha256": crop_sha256,
                    }
                )
                current = db.get(sample_id)
                if (
                    previous
                    and previous.get("status") != "pending"
                    and current
                    and current.get("status") == "pending"
                ):
                    changed_review_count += 1
                added += int(inserted)
                refreshed += int(not inserted)
                dynamic_count += int(location.method.startswith("dynamic_"))
                fallback_count += int(location.method in {"fixed_roi", "fixed_fallback"})
                source_diagnostics["fields"].append(
                    {
                        "field_key": field.key,
                        "panel": field.panel,
                        "method": location.method,
                        "locator_confidence": location.locator_confidence,
                        "matched_label": location.matched_label,
                        "box": box.to_list(),
                        "raw_ocr": raw_text,
                        "raw_confidence": round(confidence, 4),
                    }
                )
            (diagnostics_root / f"{decoded.source_id}.json").write_text(
                json.dumps(source_diagnostics, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            measurements = {
                str(item["field_key"]): {
                    "raw_text": item["raw_ocr"],
                    "confidence": item["raw_confidence"],
                    "extraction_method": item["method"],
                    "locator_confidence": item["locator_confidence"],
                }
                for item in source_diagnostics["fields"]
            }
            extracted_payload = {
                "schema_version": "1.0",
                "source_id": decoded.source_id,
                "profile": config.profile.name,
                "study_info": study_info.as_dict(),
                "measurements": measurements,
            }
            (extracted_output_root / f"{decoded.source_id}.json").write_text(
                json.dumps(extracted_payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            failed += 1
            LOGGER.exception("Could not collect training crops for input item %d", source_index)

    manifest = {
        "created_at": utc_now(),
        "input_items": len(sources),
        "fields_per_item": field_count,
        "added_samples": added,
        "refreshed_samples": refreshed,
        "failed_items": failed,
        "dynamic_samples": dynamic_count,
        "fixed_or_fallback_samples": fallback_count,
        "reviews_invalidated_by_changed_crop": changed_review_count,
        "locator_mode": "dynamic" if dynamic_enabled else "fixed",
        "locator_engine": locator_engine.info() if locator_engine else None,
        "recognition_engine": engine.info(),
        "profile": config.profile.name,
        "diagnostics": {
            "json_directory": "collection_diagnostics",
            "overlay_directory": "locator_overlays",
            "source_render_directory": "source_renders",
            "header_crop_directory": "header_crops",
            "extracted_output_directory": "extracted_output",
            "header_normalization_model": (
                "header_normalization/model.json" if header_alias_model_path.is_file() else None
            ),
            "learned_header_aliases": sum(len(values) for values in learned_header_aliases.values()),
        },
        "privacy": {
            "source_filenames_stored": False,
            "dicom_identifiers_stored": False,
            "source_id": "first 24 hexadecimal characters of SHA-256 over source bytes",
        },
    }
    (root / "collection_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest
