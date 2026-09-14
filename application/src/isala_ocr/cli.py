from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .logging_utils import configure_logging
from .model_prep import download_models
from .ocr import create_engine
from .ocr.paddle import PaddleEngine
from .ocr.recognition import PaddleRecognitionEngine
from .ocr.tesseract import TesseractEngine
from .pipeline import process_file
from .training.collector import collect_mapping_detections, collect_samples
from .training.source_preview import prepare_source_renders
from .training.dataset import build_dataset
from .training.db import TrainingDatabase, utc_now
from .training.evaluator import compare_evaluations, evaluate_model
from .training.model_registry import activate_model, register_model
from .training.mapping import (
    auto_confirm_mapping_suggestions, materialize_confirmed_mappings,
    recognize_approved_mapped_samples,
)
from .training.localization import passes_detection_gate
from .training.projects import (
    project_active_recognition_dir, resolve_project_registry, resolve_project_workspace,
)
from .training.localization_dataset import (
    build_localization_dataset, compare_localization_evaluations,
    detection_quality_report, diagnose_prediction_file, evaluate_candidate_detector,
    evaluate_prediction_file, localization_ground_truth_fingerprint, merge_localization_predictions,
    validate_localization_dataset,
)
from .training.table_cell_training import (
    activate_table_cell_model, active_table_cell_model, build_table_cell_dataset, evaluate_table_cell_predictions,
    register_table_cell_model, validate_table_cell_dataset,
)
from .training.table_region_training import build_table_region_dataset

LOGGER = logging.getLogger(__name__)


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


def _process(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device
    engine = create_engine(config.ocr, override=args.engine)
    sources = _files(Path(args.input))
    if not sources:
        LOGGER.error("No input files found")
        return 2

    failed = 0
    review = 0
    for item_index, source in enumerate(sources, start=1):
        try:
            result = process_file(source, args.output, config, engine)
            if result.status != "ok":
                review += 1
        except Exception:
            failed += 1
            LOGGER.exception("Processing failed for input item %d", item_index)
            if args.fail_fast:
                break
    LOGGER.info("Batch complete: total=%d review=%d failed=%d", len(sources), review, failed)
    return 1 if failed else 0


def _validate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    summary = {
        "config": str(config.path),
        "profile": config.profile.name,
        "reference_size": [config.profile.reference_width, config.profile.reference_height],
        "anchors": len(config.profile.anchors),
        "fields": len(config.profile.fields),
        "consistency_rules": len(config.profile.consistency_rules),
        "ocr_provider": config.ocr.get("provider", "paddle"),
        "training": config.raw.get("training", {}),
    }
    print(json.dumps(summary, indent=2))
    return 0


def _download(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    baseline_model = (
        config.raw.get("training", {}).get("model", {}).get("default")
    )
    manifest = download_models(
        config.ocr,
        additional_recognition_models=[baseline_model] if baseline_model else [],
        table_structure_settings=(
            config.raw.get("training", {}).get("collection", {}).get("table_structure", {})
        ),
    )
    print(json.dumps(manifest, indent=2))
    return 0


def _training_workspace(
    config,
    override: str | None,
    *,
    configure_active_recognition: bool = True,
) -> Path:
    """Resolve the active project workspace.

    Localization-only commands deliberately pass ``configure_active_recognition=False``.
    Those commands run in the read-only dataset-builder container and neither need nor
    should mutate the recognition-model namespace under /models. Recognition-aware
    commands keep the historic project-specific active-model setup.
    """
    base = Path(override or config.raw.get("training", {}).get("workspace", "/training/workspace"))
    workspace = resolve_project_workspace(base)
    if configure_active_recognition:
        active_dir = str(config.raw.get("ocr", {}).get("active_recognition_model_dir", "/models/active-recognition"))
        active_path = Path(active_dir)
        models_root = active_path.parent if active_path.name == "active-recognition" else Path("/models")
        config.raw.setdefault("ocr", {})["active_recognition_model_dir"] = str(
            project_active_recognition_dir(models_root, base)
        )
    return workspace


def _localization_workspace(config, override: str | None) -> Path:
    """Resolve a localization workspace without touching /models."""
    return _training_workspace(config, override, configure_active_recognition=False)


def _training_registry(config, override: str | None, workspace_override: str | None = None) -> Path:
    registry_base = Path(override or config.raw.get("training", {}).get("registry", "/training/registry"))
    workspace_base = Path(workspace_override or config.raw.get("training", {}).get("workspace", "/training/workspace"))
    return resolve_project_registry(registry_base, workspace_base)


def _mapping_workspace(config, workspace_override: str | None = None) -> Path:
    """Resolve the Mapping workspace without applying the global detection gate.

    Mapping is Pipeline B.  In table-first mode it can use already persisted
    relations and their per-relation ROI diagnostics while other GT sources
    are still open.  The materializer remains responsible for rejecting an
    individual mapping whose value geometry is unavailable.
    """
    return _training_workspace(config, workspace_override)


def _collect_training(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _training_workspace(config, args.workspace)
    flow = str(config.raw.get("training", {}).get("collection", {}).get("flow", "")).strip().lower()
    if flow != "generic_mapping":
        raise RuntimeError(
            "IsalaOCR 3.7 Pipeline A requires training.collection.flow=generic_mapping; "
            "legacy profile extraction is not allowed in the field-detection action."
        )
    if args.render_only:
        print(json.dumps(prepare_source_renders(args.input, workspace, config), indent=2))
        return 0
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device
    if args.model:
        config.raw.setdefault("ocr", {})["recognition_model"] = args.model
    locator_mode = args.locator or str(
        config.raw.get("training", {}).get("collection", {}).get("locator", "dynamic")
    )
    locator_engine = None
    if args.engine == "tesseract":
        recognition_settings = dict(config.ocr.get("tesseract", config.ocr))
        recognition_settings["page_segmentation_mode"] = 7
        engine = TesseractEngine(recognition_settings)
        if locator_mode != "fixed":
            locator_settings = dict(recognition_settings)
            locator_settings["page_segmentation_mode"] = 6
            locator_engine = TesseractEngine(locator_settings)
    else:
        engine = PaddleRecognitionEngine(config.ocr)
        if locator_mode != "fixed":
            # Label localization must keep the official general-purpose
            # recognition model. A custom value-only model may recognize
            # digits well but degrade screen-label text such as "Stroke Volume".
            locator_settings = dict(config.ocr)
            locator_settings.pop("active_recognition_model_dir", None)
            locator_settings["recognition_model"] = str(
                config.raw.get("training", {})
                .get("collection", {})
                .get("locator_recognition_model", "PP-OCRv6_small_rec")
            )
            locator_engine = PaddleEngine(locator_settings)
    manifest = collect_samples(
        args.input,
        workspace,
        config,
        engine,
        padding_pixels=args.padding,
        locator_engine=locator_engine,
        locator_mode=locator_mode,
        table_model_id=args.table_model_id,
        source_id=args.source_id,
        region_only=bool(getattr(args, "regions_only", False)),
    )
    print(json.dumps(manifest, indent=2))
    return 1 if manifest["failed_items"] else 0



def _collect_mapping(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device
    recognition_engine = PaddleRecognitionEngine(config.ocr)
    locator_settings = dict(config.ocr)
    locator_settings.pop("active_recognition_model_dir", None)
    locator_settings["recognition_model"] = str(
        config.raw.get("training", {}).get("collection", {}).get("locator_recognition_model", "PP-OCRv6_small_rec")
    )
    locator_engine = PaddleEngine(locator_settings)
    manifest = collect_mapping_detections(
        args.input,
        _training_workspace(config, args.workspace),
        config,
        locator_engine,
        recognition_engine,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 1 if manifest.get("failed_items") else 0


def _run_application_pipeline(args: argparse.Namespace) -> int:
    """Run one DICOM through active detection, mapping and value output."""
    config = load_config(args.config)
    workspace = _mapping_workspace(config, args.workspace)
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if input_path.is_file() and input_path.suffix.lower() != ".dcm":
        raise ValueError("Application pipeline accepts DICOM files only (.dcm)")
    input_files = [item for item in _files(input_path) if item.suffix.lower() == ".dcm"]
    if input_path.is_dir():
        selection_path = workspace / "input_selection.json"
        selected = json.loads(selection_path.read_text(encoding="utf-8-sig")).get("selected", []) if selection_path.is_file() else []
        selected_paths = {str(value).replace("\\", "/") for value in selected}
        if selected_paths:
            input_files = [
                item for item in input_files
                if item.resolve().as_posix().replace("/input/", "", 1) in selected_paths
                or item.name in selected_paths
            ]
    if len(input_files) != 1:
        raise ValueError("Application pipeline expects exactly one selected DICOM input")
    source_id = hashlib.sha256(input_files[0].read_bytes()).hexdigest()[:24]
    requested_source_id = str(args.source_id or "").strip()
    if requested_source_id and requested_source_id != source_id:
        raise ValueError("Aangeboden source-id hoort niet bij het geselecteerde DICOM-bestand")

    engine = PaddleRecognitionEngine(config.ocr)
    locator_settings = dict(config.ocr)
    locator_settings.pop("active_recognition_model_dir", None)
    locator_settings["recognition_model"] = str(
        config.raw.get("training", {}).get("collection", {}).get(
            "locator_recognition_model", "PP-OCRv6_small_rec"
        )
    )
    # The generic_mapping dispatcher requires a locator engine even in
    # table-first mode.  Table-first keeps it out of Pipeline-A geometry, but
    # the same neutral OCR locator is still needed for the semantic mapping
    # stage that follows.
    locator_engine = PaddleEngine(locator_settings)
    detection = collect_samples(
        input_path, workspace, config, engine,
        locator_engine=locator_engine, locator_mode="fixed",
        table_model_id=(args.table_model_id or "active"),
    )
    if int(detection.get("failed_items") or 0) or int(detection.get("detected_sources") or 0) != 1:
        raise RuntimeError(f"DICOM-detectie niet volledig geslaagd: {detection}")
    active_table_model = active_table_cell_model(workspace) or {}

    # The canonical-GT route remains the training/review path. For a new
    # deployment DICOM, mapping consumes active inference geometry instead.
    config.raw.setdefault("training", {}).setdefault("localization", {})["strategy"] = "fusion"
    mapping = collect_mapping_detections(input_path, workspace, config, locator_engine, engine)
    if int(mapping.get("failed_items") or 0):
        raise RuntimeError(f"Mappingvoorbereiding niet volledig geslaagd: {mapping}")

    database = TrainingDatabase(workspace / "samples.sqlite3")
    if args.mapping_profile_id:
        from .training.mapping import apply_mapping_profile
        apply_mapping_profile(database, str(args.mapping_profile_id), source_id)
    promoted = auto_confirm_mapping_suggestions(
        database, source_id, minimum_score=float(args.minimum_mapping_confidence)
    )
    confirmed = database.list_mappings(source_id, status="confirmed")
    if not promoted and not confirmed:
        raise RuntimeError(
            "Geen ondubbelzinnige mappings boven de automatische drempel; "
            "output wordt niet aangemaakt. Open Mapping Studio voor review."
        )
    materialized = materialize_confirmed_mappings(
        workspace, config, None, source_id=source_id, recognize=False
    )
    if int(materialized.get("failed_sources") or 0):
        raise RuntimeError(f"Waarde-crops konden niet volledig worden gemaakt: {materialized}")
    recognition = recognize_approved_mapped_samples(workspace, engine, source_id=source_id)
    if int(recognition.get("recognized_samples") or 0) <= 0:
        raise RuntimeError(f"Geen waarden herkend: {recognition}")

    # Make the final data block self-describing.  The result must be traceable
    # to the exact active model bundle, dataset and mapping decision that
    # produced it, without storing the original DICOM filename or headers.
    registry_active: dict[str, object] = {}
    registry_root = _training_registry(config, None, args.workspace)
    registry_file = registry_root / "active.json"
    try:
        payload = json.loads(registry_file.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            registry_active = payload
        registry_index = json.loads((registry_root / "registry.json").read_text(encoding="utf-8-sig"))
        active_id = str(registry_active.get("model_id") or "")
        if isinstance(registry_index, dict) and active_id:
            registered = next(
                (item for item in registry_index.get("models", [])
                 if isinstance(item, dict) and str(item.get("model_id") or "") == active_id),
                None,
            )
            if isinstance(registered, dict):
                registry_active = {**registered, **registry_active}
    except (OSError, TypeError, ValueError):
        LOGGER.warning("Active Recognition registry could not be read: %s", registry_file)
    output_path = workspace / "extracted_output" / f"{source_id}.json"
    if output_path.is_file():
        output_payload = json.loads(output_path.read_text(encoding="utf-8"))
        if not isinstance(output_payload, dict):
            raise RuntimeError("Generated output block is not a JSON object")
        output_payload["provenance"] = {
            "input_format": "DICOM",
            "source_id": source_id,
            "source_filename_stored": False,
            "dicom_headers_stored": False,
            "active_models": {
                "table_cell": active_table_model or detection.get("active_table_cell_model") or {},
                "recognition": registry_active or engine.info(),
                "locator_ocr": mapping.get("locator_engine") or {},
                "table_structure": mapping.get("table_structure_engine") or {},
            },
            "datasets": {
                "table_cell": str(active_table_model.get("dataset_id") or ""),
                "recognition": registry_active.get("dataset_id", ""),
            },
            "mapping": {
                "profile_id": str(args.mapping_profile_id or ""),
                "mode": "profile_plus_active_schema_matching" if args.mapping_profile_id else "active_schema_matching",
                "auto_confirmed_count": len(promoted),
                "confirmed_count": len(confirmed),
                "minimum_confidence": float(args.minimum_mapping_confidence),
            },
            "pipeline": [
                "DICOM intake",
                "active table/cell geometry",
                "semantic OCR and table relations",
                "mapping profile and active schema matching",
                "approved ROI materialization",
                "active Recognition value extraction",
            ],
        }
        output_path.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (workspace / "application_pipeline_manifest.json").write_text(
            json.dumps({
                "created_at": utc_now(),
                "source_id": source_id,
                "input_format": "DICOM",
                "output_path": f"extracted_output/{source_id}.json",
                "provenance": output_payload["provenance"],
                "stages": {"detection": detection, "mapping": mapping, "materialized": materialized, "recognition": recognition},
            }, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps({
        "source_id": source_id,
        "active_table_model": active_table_model.get("model_id") or args.table_model_id or "active",
        "mapping_profile_id": str(args.mapping_profile_id or ""),
        "auto_confirmed_mappings": len(promoted),
        "confirmed_mappings_used": len(confirmed),
        "detection": detection,
        "mapping": mapping,
        "materialized": materialized,
        "recognition": recognition,
        "output_path": f"extracted_output/{source_id}.json",
        "provenance_path": "application_pipeline_manifest.json",
    }, indent=2, ensure_ascii=False))
    return 0


def _build_localization_dataset_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_localization_dataset(_localization_workspace(config, args.workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _validate_localization_dataset_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = validate_localization_dataset(_localization_workspace(config, args.workspace), args.dataset)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") == "ok" else 2


def _build_table_cell_dataset_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_table_cell_dataset(_localization_workspace(config, args.workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _build_table_region_dataset_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = build_table_region_dataset(_localization_workspace(config, args.workspace))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _validate_table_cell_dataset_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = validate_table_cell_dataset(_localization_workspace(config, args.workspace), args.dataset)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("valid") else 2


def _evaluate_table_cell_predictions_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = evaluate_table_cell_predictions(
        _localization_workspace(config, args.workspace), args.predictions,
        dataset_id=args.dataset_id, split=args.split, confidence=float(args.minimum_confidence),
        iou_threshold=float(args.iou_threshold),
    )
    output = Path(args.output) if args.output else None
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _register_table_cell_model_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    evaluation = {}
    if args.evaluation:
        try:
            evaluation = json.loads(Path(args.evaluation).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            evaluation = {}
    result = register_table_cell_model(
        _localization_workspace(config, args.workspace), model_id=args.model_id, run_id=args.run_id,
        dataset_id=args.dataset_id, inference_dir=args.model_dir, device=args.device, evaluation=evaluation,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _activate_table_cell_model_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = activate_table_cell_model(_localization_workspace(config, args.workspace), args.model_id)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _evaluate_localization_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    thresholds = dict(config.raw.get("training", {}).get("localization", {}).get("gate", {}) or {})
    result = evaluate_candidate_detector(
        _localization_workspace(config, args.workspace),
        kind=args.kind,
        source_kind=args.source_kind,
        iou_threshold=float(args.iou_threshold),
        thresholds=thresholds,
        model_id=args.model_id or "",
        dataset_id=args.dataset_id or "",
        split=args.split,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _compare_localization_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    result = compare_localization_evaluations(
        _localization_workspace(config, args.workspace),
        dataset_id=args.dataset_id or "", model_id=args.model_id or "",
        baseline_evaluation_id=args.baseline_evaluation_id or "",
        trained_evaluation_id=args.trained_evaluation_id or "",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _register_localization_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _localization_workspace(config, args.workspace)
    db = TrainingDatabase(workspace / "samples.sqlite3")
    current_dataset_id = ""
    pointer = workspace / "localization_datasets" / "latest.txt"
    if pointer.is_file():
        current_dataset_id = pointer.read_text(encoding="utf-8-sig").strip()
    evaluations = db.list_localization_evaluations("trained")
    requested_model_id = str(args.model_id or "")
    evaluation = next((
        item for item in evaluations
        if (not requested_model_id or str(item.get("model_id") or "") == requested_model_id)
        and (not current_dataset_id or str(item.get("dataset_id") or "") == current_dataset_id)
        and str(item.get("split") or "test") == "test"
    ), None)
    if evaluation is None:
        raise ValueError("No current test evaluation exists for the selected field detector on the active localization dataset")
    metrics = evaluation.get("metrics") or {}
    model_id = requested_model_id or f"field-detector-{evaluation['evaluation_id']}"
    payload = {
        "model_id": model_id,
        "model_name": args.model_name,
        "path": args.model_dir,
        "device": args.device,
        "dataset_id": evaluation.get("dataset_id") or "",
        "metrics": metrics,
        "status": "registered",
    }
    thresholds = dict(config.raw.get("training", {}).get("localization", {}).get("gate", {}) or {})
    passed, failures = passes_detection_gate(metrics, thresholds)
    model_dir = Path(args.model_dir)
    if not model_dir.is_dir():
        raise ValueError(f"Localization model directory does not exist: {model_dir}")
    if args.activate:
        if str(evaluation.get("model_id") or "") not in {"", model_id}:
            raise ValueError("Latest trained localization evaluation belongs to a different field model")
        evaluation_fingerprint = str((evaluation.get("metrics") or {}).get("ground_truth_fingerprint") or "")
        current_fingerprint = localization_ground_truth_fingerprint(
            workspace, dataset_id=str(evaluation.get("dataset_id") or ""), split=str(evaluation.get("split") or "test")
        )
        if not evaluation_fingerprint or evaluation_fingerprint != current_fingerprint:
            raise ValueError(
                "Localization model cannot be activated because the latest trained evaluation is stale for the current ground truth/split. "
                "Run Stap 5 - Evalueren & vergelijken again."
            )
        if not passed:
            raise ValueError(
                "Localization model cannot be activated because the hard detection gate failed: "
                + "; ".join(failures)
            )
    db.register_localization_model(payload, activate=args.activate)
    if args.activate:
        db.set_detection_gate(
            True,
            reason="Active field detector passed localization gate",
            evaluation_id=str(evaluation.get("evaluation_id") or ""),
        )
        pointer_dir = workspace / "localization_models"
        pointer_dir.mkdir(parents=True, exist_ok=True)
        (pointer_dir / "active.json").write_text(
            json.dumps({**payload, "active": True}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(json.dumps({**payload, "active": bool(args.activate)}, indent=2))
    return 0


def _evaluate_localization_predictions_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _localization_workspace(config, args.workspace)
    thresholds = dict(config.raw.get("training", {}).get("localization", {}).get("gate", {}) or {})
    result = evaluate_prediction_file(
        workspace, args.predictions, model_id=args.model_id, dataset_id=args.dataset_id or "",
        iou_threshold=float(args.iou_threshold), minimum_confidence=float(args.minimum_confidence),
        thresholds=thresholds, split=args.split,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # A below-threshold model is a valid completed evaluation; it simply may not
    # be activated. Keep the worker job successful so the user can inspect metrics.
    return 0


def _diagnose_localization_predictions_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _localization_workspace(config, args.workspace)
    gate_thresholds = dict(config.raw.get("training", {}).get("localization", {}).get("gate", {}) or {})
    confidence_thresholds = [float(value) for value in str(args.thresholds).split(",") if str(value).strip()]
    requested_splits = tuple(
        value.strip().lower() for value in str(args.splits).split(",") if value.strip()
    )
    if not requested_splits or any(value not in {"train", "val", "test"} for value in requested_splits):
        raise ValueError("--splits must contain one or more of: train,val,test")
    result = diagnose_prediction_file(
        workspace, args.predictions, model_id=args.model_id, dataset_id=args.dataset_id or "",
        confidence_thresholds=confidence_thresholds, iou_threshold=float(args.iou_threshold),
        thresholds=gate_thresholds, splits=requested_splits,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _merge_localization_predictions_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    settings = dict(config.raw.get("training", {}).get("localization", {}) or {})
    result = merge_localization_predictions(
        _localization_workspace(config, args.workspace), args.predictions, model_id=args.model_id,
        minimum_confidence=float(args.minimum_confidence if args.minimum_confidence is not None else settings.get("confidence_threshold", 0.25)),
        iou_threshold=float(settings.get("fusion_iou_threshold", 0.55)),
        containment_threshold=float(settings.get("fusion_containment_threshold", 0.92)),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _detection_quality_report_cmd(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    thresholds = dict(config.raw.get("training", {}).get("localization", {}).get("gate", {}) or {})
    result = detection_quality_report(_localization_workspace(config, args.workspace), thresholds=thresholds)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _apply_mappings(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _mapping_workspace(config, args.workspace)
    manifest = materialize_confirmed_mappings(
        workspace,
        config,
        None,
        source_id=args.source_id,
        padding_pixels=args.padding,
        recognize=False,
        reuse_existing_recognition=True,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 1 if manifest.get("failed_sources") else 0


def _read_mapped_values(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _mapping_workspace(config, args.workspace)
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device
    if args.model:
        config.raw.setdefault("ocr", {})["recognition_model"] = args.model
    if args.engine == "tesseract":
        settings = dict(config.ocr.get("tesseract", config.ocr))
        settings["page_segmentation_mode"] = 7
        engine = TesseractEngine(settings)
    else:
        engine = PaddleRecognitionEngine(config.ocr)
    manifest = recognize_approved_mapped_samples(
        workspace,
        engine,
        source_id=args.source_id,
        batch_size=args.batch_size,
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 1 if manifest.get("failed_samples") else 0


def _label_training(args: argparse.Namespace) -> int:
    from .training.labeler import serve_labeler

    config = load_config(args.config)
    serve_labeler(
        _training_workspace(config, args.workspace), host=args.host, port=args.port
    )
    return 0


def _training_status(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    workspace = _training_workspace(config, args.workspace)
    db = TrainingDatabase(workspace / "samples.sqlite3")
    payload = {
        "workspace": str(workspace),
        "counts": db.counts(),
        "fields": db.fields(),
        "latest_dataset": (
            (workspace / "datasets" / "latest.txt").read_text(encoding="utf-8").strip()
            if (workspace / "datasets" / "latest.txt").exists()
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _build_dataset(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    # Recognition training consumes only accepted Recognition-GT samples. It
    # is independent from the table/field geometry gate and open GT sources
    # are naturally excluded by the accepted-sample query in build_dataset.
    workspace = _training_workspace(config, args.workspace, configure_active_recognition=False)
    settings = config.raw.get("training", {}).get("dataset", {})
    manifest = build_dataset(
        workspace,
        train_ratio=args.train_ratio if args.train_ratio is not None else float(settings.get("train_ratio", 0.70)),
        val_ratio=args.val_ratio if args.val_ratio is not None else float(settings.get("validation_ratio", 0.15)),
        test_ratio=args.test_ratio if args.test_ratio is not None else float(settings.get("test_ratio", 0.15)),
        augmentations_per_train_sample=(
            args.augmentations
            if args.augmentations is not None
            else int(settings.get("augmentations_per_train_sample", 2))
        ),
        split_salt=str(settings.get("split_salt", "isala-ocr-v1")),
        minimum_samples=(
            args.minimum_samples
            if args.minimum_samples is not None
            else int(settings.get("minimum_samples", 32))
        ),
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return 0


def _resolve_dataset(workspace: Path, value: str) -> Path:
    if value == "latest":
        latest = workspace / "datasets" / "latest.txt"
        if not latest.is_file():
            raise FileNotFoundError("No latest dataset pointer exists")
        value = latest.read_text(encoding="utf-8").strip()
    path = Path(value)
    return path if path.is_absolute() else workspace / "datasets" / value


def _evaluate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    # Recognition evaluation belongs to Pipeline B and consumes the accepted
    # Recognition-GT dataset. It must not depend on the legacy Step-4 field
    # localization/detection gate.
    workspace = _training_workspace(config, args.workspace, configure_active_recognition=False)
    dataset = _resolve_dataset(workspace, args.dataset)
    if args.device:
        config.raw.setdefault("ocr", {})["device"] = args.device
    if args.model_name:
        ocr_settings = config.raw.setdefault("ocr", {})
        ocr_settings["recognition_model"] = args.model_name
        # A baseline requested by model name must not silently resolve to an
        # activated or configured custom model directory.
        ocr_settings.pop("active_recognition_model_dir", None)
        ocr_settings.pop("recognition_model_dir", None)
    report = evaluate_model(
        dataset,
        config.ocr,
        args.output,
        model_dir=args.model_dir,
        split=args.split,
        batch_size=args.batch_size,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


def _compare(args: argparse.Namespace) -> int:
    report = compare_evaluations(args.baseline, args.custom, args.output)
    print(json.dumps(report, indent=2))
    # A valid comparison is a successful task, regardless of which model wins.
    # The verdict is data in comparison.json and must not mark the worker job as failed.
    return 0


def _register(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    manifest = register_model(
        _training_registry(config, args.registry, args.workspace),
        args.run,
        args.evaluation,
        model_id=args.model_id,
    )
    print(json.dumps(manifest, indent=2))
    return 0


def _activate(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    threshold = (
        args.minimum_exact_match
        if args.minimum_exact_match is not None
        else float(
            config.raw.get("training", {})
            .get("activation", {})
            .get("minimum_exact_match", 0.95)
        )
    )
    workspace_base = Path(args.workspace or config.raw.get("training", {}).get("workspace", "/training/workspace"))
    active = activate_model(
        _training_registry(config, args.registry, args.workspace),
        args.model_root,
        args.model_id,
        minimum_exact_match=threshold,
        force=args.force,
        active_destination=project_active_recognition_dir(args.model_root, workspace_base),
    )
    print(json.dumps(active, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isala-ocr",
        description="Fully local OCR extraction and recognition-model training for DICOM screenshots.",
    )
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    process_parser = subparsers.add_parser("process", help="Process a DICOM/image file or directory")
    process_parser.add_argument("--input", required=True)
    process_parser.add_argument("--output", required=True)
    process_parser.add_argument("--config", default="/app/config/app.yaml")
    process_parser.add_argument("--engine", choices=["paddle", "tesseract"])
    process_parser.add_argument("--device", help="Paddle device, for example cpu or gpu:0")
    process_parser.add_argument("--fail-fast", action="store_true")
    process_parser.set_defaults(func=_process)

    validate_parser = subparsers.add_parser("validate-config", help="Validate configuration")
    validate_parser.add_argument("--config", default="/app/config/app.yaml")
    validate_parser.set_defaults(func=_validate)

    model_parser = subparsers.add_parser(
        "download-models",
        help="Download and smoke-test PaddleOCR models into the local cache",
    )
    model_parser.add_argument("--config", default="/app/config/app.yaml")
    model_parser.set_defaults(func=_download)

    collect_parser = subparsers.add_parser(
        "collect-training", help="Pipeline A: detect neutral field-candidate geometry; do not persist values or mappings"
    )
    collect_parser.add_argument("--input", required=True)
    collect_parser.add_argument("--workspace")
    collect_parser.add_argument("--config", default="/app/config/app.yaml")
    collect_parser.add_argument("--engine", choices=["paddle-recognition", "tesseract"], default="paddle-recognition")
    collect_parser.add_argument("--model")
    collect_parser.add_argument("--table-model-id", help="Explicit table-cell model for this detection run; use generic-ppstructure for the baseline")
    collect_parser.add_argument("--source-id", help="Detect only this source from the selected input")
    collect_parser.add_argument("--regions-only", action="store_true", help="Detect table regions only; do not run cell detection")
    collect_parser.add_argument("--device")
    collect_parser.add_argument("--render-only", action="store_true", help="Create full source renders without OCR or cell detection")
    collect_parser.add_argument("--padding", type=int)
    collect_parser.add_argument(
        "--locator", choices=["dynamic", "fixed"],
        help="Locate rows from screen labels (dynamic) or use legacy fixed ROIs",
    )
    collect_parser.set_defaults(func=_collect_training)

    mapping_detect_parser = subparsers.add_parser(
        "collect-mapping", help="Pipeline B: create semantic OCR blocks and mapping relations after the detection gate"
    )
    mapping_detect_parser.add_argument("--input", required=True)
    mapping_detect_parser.add_argument("--workspace")
    mapping_detect_parser.add_argument("--config", default="/app/config/app.yaml")
    mapping_detect_parser.add_argument("--device")
    mapping_detect_parser.set_defaults(func=_collect_mapping)

    application_parser = subparsers.add_parser(
        "run-application-pipeline",
        help="Run one DICOM through active detection, mapping, crops, recognition and JSON output",
    )
    application_parser.add_argument("--input", required=True)
    application_parser.add_argument("--workspace")
    application_parser.add_argument("--config", default="/app/config/app.yaml")
    application_parser.add_argument("--source-id")
    application_parser.add_argument("--table-model-id", default="active")
    application_parser.add_argument("--mapping-profile-id", default="")
    application_parser.add_argument("--minimum-mapping-confidence", type=float, default=0.90)
    application_parser.set_defaults(func=_run_application_pipeline)

    loc_build = subparsers.add_parser("build-localization-dataset", help="Build a COCO field-localization dataset from detection reviews")
    loc_build.add_argument("--workspace")
    loc_build.add_argument("--config", default="/app/config/app.yaml")
    loc_build.set_defaults(func=_build_localization_dataset_cmd)

    loc_validate = subparsers.add_parser("validate-localization-dataset", help="Validate the latest COCO field-localization dataset")
    loc_validate.add_argument("--workspace")
    loc_validate.add_argument("--config", default="/app/config/app.yaml")
    loc_validate.add_argument("--dataset", default="latest")
    loc_validate.set_defaults(func=_validate_localization_dataset_cmd)

    table_build = subparsers.add_parser("build-table-cell-dataset", help="Build a COCO table-cell dataset from completed table reviews")
    table_build.add_argument("--workspace")
    table_build.add_argument("--config", default="/app/config/app.yaml")
    table_build.set_defaults(func=_build_table_cell_dataset_cmd)

    table_validate = subparsers.add_parser("validate-table-cell-dataset", help="Validate the latest reviewed table-cell COCO dataset")
    table_validate.add_argument("--workspace")
    table_validate.add_argument("--config", default="/app/config/app.yaml")
    table_validate.add_argument("--dataset", default="latest")
    table_validate.set_defaults(func=_validate_table_cell_dataset_cmd)

    region_build = subparsers.add_parser("build-table-region-dataset", help="Build a COCO table-region dataset from Step-2 region GT")
    region_build.add_argument("--workspace")
    region_build.add_argument("--config", default="/app/config/app.yaml")
    region_build.set_defaults(func=_build_table_region_dataset_cmd)

    table_eval = subparsers.add_parser("evaluate-table-cell-predictions", help="Evaluate a trained wireless table-cell detector on a fixed dataset split")
    table_eval.add_argument("--workspace")
    table_eval.add_argument("--config", default="/app/config/app.yaml")
    table_eval.add_argument("--predictions", required=True)
    table_eval.add_argument("--dataset-id", default="latest")
    table_eval.add_argument("--split", choices=["train", "val", "test"], default="val")
    table_eval.add_argument("--minimum-confidence", type=float, default=0.25)
    table_eval.add_argument("--iou-threshold", type=float, default=0.50)
    table_eval.add_argument("--output")
    table_eval.set_defaults(func=_evaluate_table_cell_predictions_cmd)

    table_register = subparsers.add_parser("register-table-cell-model", help="Register a trained wireless table-cell detector in the active project")
    table_register.add_argument("--workspace")
    table_register.add_argument("--config", default="/app/config/app.yaml")
    table_register.add_argument("--model-id", required=True)
    table_register.add_argument("--run-id", required=True)
    table_register.add_argument("--dataset-id", required=True)
    table_register.add_argument("--model-dir", required=True)
    table_register.add_argument("--device", default="gpu")
    table_register.add_argument("--evaluation")
    table_register.set_defaults(func=_register_table_cell_model_cmd)

    table_activate = subparsers.add_parser("activate-table-cell-model", help="Activate a registered table-cell detector for future table runs")
    table_activate.add_argument("--workspace")
    table_activate.add_argument("--config", default="/app/config/app.yaml")
    table_activate.add_argument("--model-id", default="latest")
    table_activate.set_defaults(func=_activate_table_cell_model_cmd)

    loc_eval = subparsers.add_parser("evaluate-localization", help="Evaluate detector geometry against reviewed localization annotations")
    loc_eval.add_argument("--workspace")
    loc_eval.add_argument("--config", default="/app/config/app.yaml")
    loc_eval.add_argument("--kind", choices=["baseline", "trained"], default="baseline")
    loc_eval.add_argument("--source-kind")
    loc_eval.add_argument("--model-id")
    loc_eval.add_argument("--dataset-id")
    loc_eval.add_argument("--iou-threshold", type=float, default=0.75)
    loc_eval.add_argument("--split", choices=["train", "val", "test", "reviewed"], default="test")
    loc_eval.set_defaults(func=_evaluate_localization_cmd)

    loc_pred_eval = subparsers.add_parser("evaluate-localization-predictions", help="Evaluate trained detector prediction JSON against localization ground truth")
    loc_pred_eval.add_argument("--workspace")
    loc_pred_eval.add_argument("--config", default="/app/config/app.yaml")
    loc_pred_eval.add_argument("--predictions", required=True)
    loc_pred_eval.add_argument("--model-id", required=True)
    loc_pred_eval.add_argument("--dataset-id")
    loc_pred_eval.add_argument("--iou-threshold", type=float, default=0.75)
    loc_pred_eval.add_argument("--minimum-confidence", type=float, default=0.25)
    loc_pred_eval.add_argument("--split", choices=["train", "val", "test", "reviewed"], default="test")
    loc_pred_eval.set_defaults(func=_evaluate_localization_predictions_cmd)

    loc_diag = subparsers.add_parser("diagnose-localization-predictions", help="Sweep confidence thresholds across train/val/test for a trained field detector")
    loc_diag.add_argument("--workspace")
    loc_diag.add_argument("--config", default="/app/config/app.yaml")
    loc_diag.add_argument("--predictions", required=True)
    loc_diag.add_argument("--model-id", required=True)
    loc_diag.add_argument("--dataset-id")
    loc_diag.add_argument("--iou-threshold", type=float, default=0.75)
    loc_diag.add_argument("--thresholds", default="0.01,0.05,0.10,0.15,0.20,0.25,0.35,0.50,0.60,0.70,0.80,0.90,0.95")
    loc_diag.add_argument("--splits", default="train,val,test", help="Comma-separated diagnostic splits. Use train,val during model development; reserve test for the final hold-out evaluation.")
    loc_diag.set_defaults(func=_diagnose_localization_predictions_cmd)

    loc_merge = subparsers.add_parser("merge-localization-predictions", help="Fuse active field-detector predictions into neutral Pipeline A candidates")
    loc_merge.add_argument("--workspace")
    loc_merge.add_argument("--config", default="/app/config/app.yaml")
    loc_merge.add_argument("--predictions", required=True)
    loc_merge.add_argument("--model-id", required=True)
    loc_merge.add_argument("--minimum-confidence", type=float)
    loc_merge.set_defaults(func=_merge_localization_predictions_cmd)

    loc_report = subparsers.add_parser("detection-quality-report", help="Write and print the Pipeline A detection quality report")
    loc_report.add_argument("--workspace")
    loc_report.add_argument("--config", default="/app/config/app.yaml")
    loc_report.set_defaults(func=_detection_quality_report_cmd)

    loc_compare = subparsers.add_parser("compare-localization", help="Compare latest baseline and trained localization evaluations")
    loc_compare.add_argument("--workspace")
    loc_compare.add_argument("--config", default="/app/config/app.yaml")
    loc_compare.add_argument("--dataset-id")
    loc_compare.add_argument("--model-id")
    loc_compare.add_argument("--baseline-evaluation-id")
    loc_compare.add_argument("--trained-evaluation-id")
    loc_compare.set_defaults(func=_compare_localization_cmd)

    loc_register = subparsers.add_parser("register-localization-model", help="Register or activate the trained field detector")
    loc_register.add_argument("--workspace")
    loc_register.add_argument("--config", default="/app/config/app.yaml")
    loc_register.add_argument("--model-id")
    loc_register.add_argument("--model-name", default="PicoDet-S")
    loc_register.add_argument("--model-dir", required=True)
    loc_register.add_argument("--device", default="cpu")
    loc_register.add_argument("--activate", action="store_true")
    loc_register.set_defaults(func=_register_localization_cmd)

    apply_parser = subparsers.add_parser(
        "apply-mappings",
        help="Materialize confirmed generic field mappings as ROI crops",
    )
    apply_parser.add_argument("--workspace")
    apply_parser.add_argument("--config", default="/app/config/app.yaml")
    apply_parser.add_argument("--engine", choices=["paddle-recognition", "tesseract"], default="paddle-recognition")
    apply_parser.add_argument("--model")
    apply_parser.add_argument("--device")
    apply_parser.add_argument("--source-id")
    apply_parser.add_argument("--padding", type=int, default=2)
    apply_parser.set_defaults(func=_apply_mappings)

    read_parser = subparsers.add_parser(
        "read-mapped-values",
        help="Recognize values from mapped ROI crops after ROI approval",
    )
    read_parser.add_argument("--workspace")
    read_parser.add_argument("--config", default="/app/config/app.yaml")
    read_parser.add_argument("--engine", choices=["paddle-recognition", "tesseract"], default="paddle-recognition")
    read_parser.add_argument("--model")
    read_parser.add_argument("--device")
    read_parser.add_argument("--source-id")
    read_parser.add_argument("--batch-size", type=int, default=64)
    read_parser.set_defaults(func=_read_mapped_values)

    label_parser = subparsers.add_parser("label-training", help="Start the local exact-transcription UI")
    label_parser.add_argument("--workspace")
    label_parser.add_argument("--config", default="/app/config/app.yaml")
    label_parser.add_argument("--host", default="0.0.0.0")
    label_parser.add_argument("--port", type=int, default=8088)
    label_parser.set_defaults(func=_label_training)

    status_parser = subparsers.add_parser("training-status", help="Show local sample and dataset counts")
    status_parser.add_argument("--workspace")
    status_parser.add_argument("--config", default="/app/config/app.yaml")
    status_parser.set_defaults(func=_training_status)

    dataset_parser = subparsers.add_parser("build-dataset", help="Build grouped train/val/test recognition data")
    dataset_parser.add_argument("--workspace")
    dataset_parser.add_argument("--config", default="/app/config/app.yaml")
    dataset_parser.add_argument("--train-ratio", type=float)
    dataset_parser.add_argument("--val-ratio", type=float)
    dataset_parser.add_argument("--test-ratio", type=float)
    dataset_parser.add_argument("--augmentations", type=int)
    dataset_parser.add_argument("--minimum-samples", type=int)
    dataset_parser.set_defaults(func=_build_dataset)

    evaluate_parser = subparsers.add_parser(
        "evaluate-recognition", help="Evaluate raw recognition output against exact labels"
    )
    evaluate_parser.add_argument("--dataset", default="latest")
    evaluate_parser.add_argument("--workspace")
    evaluate_parser.add_argument("--config", default="/app/config/app.yaml")
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.add_argument("--model-name")
    evaluate_parser.add_argument("--model-dir")
    evaluate_parser.add_argument("--device")
    evaluate_parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    evaluate_parser.add_argument("--batch-size", type=int, default=32)
    evaluate_parser.set_defaults(func=_evaluate)

    compare_parser = subparsers.add_parser("compare-evaluations", help="Compare baseline and custom metrics")
    compare_parser.add_argument("--baseline", required=True)
    compare_parser.add_argument("--custom", required=True)
    compare_parser.add_argument("--output", required=True)
    compare_parser.set_defaults(func=_compare)

    register_parser = subparsers.add_parser("register-model", help="Register an evaluated exported model")
    register_parser.add_argument("--config", default="/app/config/app.yaml")
    register_parser.add_argument("--workspace")
    register_parser.add_argument("--registry")
    register_parser.add_argument("--run", required=True)
    register_parser.add_argument("--evaluation", required=True)
    register_parser.add_argument("--model-id")
    register_parser.set_defaults(func=_register)

    activate_parser = subparsers.add_parser("activate-model", help="Activate a registered recognition model")
    activate_parser.add_argument("--config", default="/app/config/app.yaml")
    activate_parser.add_argument("--workspace")
    activate_parser.add_argument("--registry")
    activate_parser.add_argument("--model-root", default="/models")
    activate_parser.add_argument("--model-id", required=True)
    activate_parser.add_argument("--minimum-exact-match", type=float)
    activate_parser.add_argument("--force", action="store_true")
    activate_parser.set_defaults(func=_activate)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    try:
        return int(args.func(args))
    except (ConfigError, FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        LOGGER.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
