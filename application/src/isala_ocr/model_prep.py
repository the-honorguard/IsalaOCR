from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from .ocr.paddle import PaddleEngine
from .ocr.recognition import PaddleRecognitionEngine
from .ocr.table_structure import PPStructureTableEngine


def _unique_model_names(values: Iterable[str | None]) -> list[str]:
    result: list[str] = []
    for value in values:
        name = str(value or "").strip()
        if name and name not in result:
            result.append(name)
    return result


def download_models(
    settings: dict[str, Any],
    additional_recognition_models: Iterable[str] | None = None,
    table_structure_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Download every inference model required for fully offline operation.

    The normal OCR pipeline prepares its configured detection and recognition
    models. Baseline evaluation is recognition-only and may intentionally use a
    different model (currently PP-OCRv6_medium_rec), so that model must be
    warmed separately before the evaluator is disconnected from the network.
    """

    model_root = Path(str(settings.get("model_root", "/models/paddlex"))).resolve()
    model_root.mkdir(parents=True, exist_ok=True)
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(model_root)

    effective = dict(settings)
    effective["allow_downloads"] = True
    effective.setdefault("device", "cpu")

    # Model preparation warms the shared *official* OCR cache. It must never
    # inherit an activated recognition model from a project or from the legacy
    # /models/active-recognition directory. A stale/incomplete custom export
    # would otherwise make action 1 fail before the official models are even
    # prepared. Runtime recognition still uses the active project model; only
    # this cache-warmup action deliberately ignores custom model directories.
    effective.pop("active_recognition_model_dir", None)
    effective.pop("recognition_model_dir", None)

    engine = PaddleEngine(effective)

    image = np.full((96, 720, 3), 255, dtype=np.uint8)
    cv2.putText(
        image,
        "ISALA OCR MODEL TEST 128.7 ml",
        (15, 62),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (0, 0, 0),
        2,
        cv2.LINE_AA,
    )
    try:
        tokens = engine.recognize_many([image])[0]
    except Exception as exc:
        raise RuntimeError(
            "Shared official OCR model preparation failed while warming the "
            f"{effective.get('detection_model')} + {effective.get('recognition_model')} pipeline. "
            "Activated/custom recognition models are intentionally ignored during this step. "
            f"Underlying Paddle error: {exc}"
        ) from exc

    prepared_recognition_models: list[dict[str, Any]] = []
    extra_names = _unique_model_names(additional_recognition_models or [])
    for model_name in extra_names:
        recognition_settings = dict(effective)
        recognition_settings["recognition_model"] = model_name
        # Baseline preparation must always fetch the named official model. An
        # activated custom model or configured directory must not mask it.
        recognition_settings.pop("active_recognition_model_dir", None)
        recognition_settings.pop("recognition_model_dir", None)
        recognition_engine = PaddleRecognitionEngine(recognition_settings)
        recognition_tokens = recognition_engine.recognize_many([image])[0]
        prepared_recognition_models.append(
            {
                "model": model_name,
                "engine": recognition_engine.info(),
                "smoke_test_text": " ".join(token.text for token in recognition_tokens),
            }
        )

    table_structure_manifest: dict[str, Any] | None = None
    if table_structure_settings and bool(table_structure_settings.get("enabled", True)):
        table_engine = PPStructureTableEngine(effective, table_structure_settings)
        # A compact synthetic table forces PP-StructureV3 to materialize its
        # layout/table/cell models in the offline cache during model preparation.
        table_image = np.full((240, 760, 3), 255, dtype=np.uint8)
        cv2.rectangle(table_image, (20, 20), (740, 220), (0, 0, 0), 2)
        for y in (70, 120, 170):
            cv2.line(table_image, (20, y), (740, y), (0, 0, 0), 1)
        for x in (290, 500):
            cv2.line(table_image, (x, 20), (x, 220), (0, 0, 0), 1)
        cv2.putText(table_image, "ED Volume", (35, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(table_image, "106.8 ml", (315, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        cv2.putText(table_image, "88-227 ml", (520, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        try:
            smoke = table_engine.smoke_test(table_image)
        except Exception as exc:
            raise RuntimeError(
                "PP-StructureV3 table-model preparation failed. "
                f"Underlying Paddle error: {exc}"
            ) from exc
        table_structure_manifest = {
            "role": "table_structure",
            "required": True,
            "prepared": True,
            "engine": table_engine.info(),
            "smoke_test": smoke,
        }

    engine_info = engine.info()
    required_models: list[dict[str, Any]] = [
        {
            "role": "text_detection",
            "model": str(settings.get("detection_model") or ""),
            "required": True,
            "prepared": True,
        },
        {
            "role": "full_page_recognition",
            "model": str(settings.get("recognition_model") or ""),
            "required": True,
            "prepared": True,
        },
    ]
    required_models.extend(
        {
            "role": "baseline_recognition",
            "model": str(item.get("model") or ""),
            "required": True,
            "prepared": True,
        }
        for item in prepared_recognition_models
    )
    if table_structure_manifest is not None:
        required_models.append(
            {
                "role": "table_structure",
                "model": "PP-StructureV3 table pipeline",
                "required": True,
                "prepared": True,
            }
        )
    optional_components = [
        {
            "role": "document_orientation",
            "enabled": bool(settings.get("use_doc_orientation_classify", False)),
            "prepared_with_pipeline": bool(settings.get("use_doc_orientation_classify", False)),
        },
        {
            "role": "document_unwarping",
            "enabled": bool(settings.get("use_doc_unwarping", False)),
            "prepared_with_pipeline": bool(settings.get("use_doc_unwarping", False)),
        },
        {
            "role": "textline_orientation",
            "enabled": bool(settings.get("use_textline_orientation", False)),
            "prepared_with_pipeline": bool(settings.get("use_textline_orientation", False)),
        },
    ]
    manifest = {
        "schema_version": "2.0",
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "model_root": str(model_root),
        "engine": engine_info,
        "smoke_test_text": " ".join(token.text for token in tokens),
        "required_models": required_models,
        "all_required_models_prepared": all(item["prepared"] for item in required_models),
        "optional_components": optional_components,
        "additional_recognition_models": prepared_recognition_models,
        "table_structure": table_structure_manifest,
        "files": sum(1 for item in model_root.rglob("*") if item.is_file()),
    }
    with (model_root / "isala_ocr_model_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest
