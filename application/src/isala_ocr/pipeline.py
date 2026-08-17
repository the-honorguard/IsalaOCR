from __future__ import annotations

import logging
import time
from pathlib import Path

from .config import AppConfig
from .consistency import evaluate_consistency
from .extraction import ExtractionSettings, extract
from .image_io import load_input
from .models import DocumentResult
from .ocr.base import OCREngine
from .output import write_result
from .study_info import extract_study_info
from .visualization import draw_overlay

LOGGER = logging.getLogger(__name__)


def process_file(
    source: str | Path,
    output_root: str | Path,
    config: AppConfig,
    engine: OCREngine,
) -> DocumentResult:
    source_path = Path(source)
    timings: dict[str, float] = {}
    started = time.perf_counter()

    decode_started = time.perf_counter()
    decoded = load_input(source_path, config.dicom)
    timings["decode"] = (time.perf_counter() - decode_started) * 1000

    preprocess = config.preprocessing
    extraction_settings = ExtractionSettings(
        variants=tuple(
            preprocess.get(
                "variants",
                ["grayscale_upscale", "clahe_upscale", "binary_inverted"],
            )
        ),
        upscale_factor=float(preprocess.get("upscale_factor", 4.0)),
        padding_pixels=int(preprocess.get("padding_pixels", 2)),
        minimum_confidence=float(config.ocr.get("minimum_confidence", 0.55)),
        verify_anchors=bool(preprocess.get("verify_anchors", True)),
    )

    study_info_started = time.perf_counter()
    study_info_error: str | None = None
    try:
        search_x2 = int(round(
            float(config.profile.dynamic_extraction.get("panel_search_x2", 650))
            * decoded.image.shape[1]
            / config.profile.reference_width
        ))
        study_region = decoded.image[:, : min(max(search_x2, 1), decoded.image.shape[1])]
        study_batches = engine.recognize_many([study_region])
        if len(study_batches) != 1:
            raise RuntimeError("Study-info OCR did not return one result")
        study_info = extract_study_info(study_batches[0])
    except Exception as exc:  # The primary measurement extraction must remain available.
        LOGGER.warning("Study-info extraction failed: %s", type(exc).__name__)
        study_info = extract_study_info([])
        study_info_error = type(exc).__name__
    timings["study_info_ocr"] = (time.perf_counter() - study_info_started) * 1000

    ocr_started = time.perf_counter()
    anchors, fields = extract(
        decoded.image,
        config.profile,
        engine,
        extraction_settings,
    )
    timings["ocr_and_validation"] = (time.perf_counter() - ocr_started) * 1000

    consistency = evaluate_consistency(fields, config.profile.consistency_rules)

    warnings: list[str] = []
    warnings.extend(study_info.warnings)
    if study_info_error:
        warnings.append(f"study_info_extraction_failed:{study_info_error}")
    errors: list[str] = []
    failed_anchors = [anchor.name for anchor in anchors if not anchor.passed]
    invalid_fields = [field.key for field in fields if not field.valid]
    failed_consistency = [item.name for item in consistency if item.passed is False]
    unevaluated_consistency = [item.name for item in consistency if item.passed is None]
    if failed_anchors:
        warnings.append(f"Profile anchors did not match: {', '.join(failed_anchors)}")
    if invalid_fields:
        warnings.append(f"Fields requiring review: {', '.join(invalid_fields)}")
    if failed_consistency:
        warnings.append(f"Consistency rules failed: {', '.join(failed_consistency)}")
    if unevaluated_consistency:
        warnings.append(
            f"Consistency rules not evaluated: {', '.join(unevaluated_consistency)}"
        )

    status = "ok"
    if failed_anchors:
        status = "profile_mismatch"
    elif invalid_fields or failed_consistency or unevaluated_consistency:
        status = "review_required"

    result = DocumentResult(
        schema_version="2.0",
        source_id=decoded.source_id,
        source_file=(
            source_path.name
            if bool(config.privacy.get("include_source_filename", False))
            else "redacted"
        ),
        status=status,
        engine=engine.info(),
        image={"width": decoded.image.shape[1], "height": decoded.image.shape[0]},
        safe_dicom_metadata=decoded.safe_metadata,
        profile=config.profile.name,
        anchors=anchors,
        fields=fields,
        consistency=consistency,
        warnings=warnings,
        errors=errors,
        timings_ms=timings,
        study_info=study_info,
    )
    timings["total"] = (time.perf_counter() - started) * 1000

    save_overlay = bool(config.output.get("save_overlay", True))
    overlay = draw_overlay(decoded.image, anchors, fields) if save_overlay else None
    write_result(
        result,
        output_root,
        overlay=overlay,
        include_candidates=bool(config.output.get("include_candidates", True)),
    )
    LOGGER.info("Processed source_id=%s status=%s", decoded.source_id, status)
    return result
