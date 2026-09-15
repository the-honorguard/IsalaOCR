from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..models import Box, OCRToken
from .base import OCREngine, apply_character_whitelist
from .paddlex_runtime import prepare_paddlex_runtime


class PaddleEngine(OCREngine):
    """Lazy, single-instance wrapper for PaddleOCR 3.x."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self._pipeline = None
        self._version = "unknown"
        self._load_error: Exception | None = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        if self._load_error is not None:
            raise RuntimeError("PaddleOCR initialization previously failed in this process") from self._load_error

        # Only the side effects matter here (env vars / cache dir creation);
        # the resolved model root itself is read from self.settings below.
        prepare_paddlex_runtime(self.settings)
        try:
            import paddleocr
            from paddleocr import PaddleOCR
        except ImportError as exc:
            self._load_error = exc
            raise RuntimeError(
                "PaddleOCR is not installed. Install the project with the 'paddle' extra."
            ) from exc
        except Exception as exc:
            self._load_error = exc
            raise

        self._version = getattr(paddleocr, "__version__", "unknown")

        kwargs: dict[str, Any] = {
            "use_doc_orientation_classify": bool(
                self.settings.get("use_doc_orientation_classify", False)
            ),
            "use_doc_unwarping": bool(self.settings.get("use_doc_unwarping", False)),
            "use_textline_orientation": bool(
                self.settings.get("use_textline_orientation", False)
            ),
            "device": str(self.settings.get("device", "cpu")),
            "engine": self.settings.get("inference_engine", "paddle_static"),
            "cpu_threads": int(self.settings.get("cpu_threads", 8)),
            "enable_mkldnn": bool(self.settings.get("enable_mkldnn", True)),
            "text_rec_score_thresh": float(self.settings.get("recognition_threshold", 0.0)),
        }
        optional_keys = {
            "ocr_version": "version",
            "text_detection_model_name": "detection_model",
            "text_recognition_model_name": "recognition_model",
            "text_detection_model_dir": "detection_model_dir",
            "text_recognition_model_dir": "recognition_model_dir",
        }
        active_recognition = self.settings.get("active_recognition_model_dir")
        if active_recognition:
            active_path = Path(str(active_recognition))
            model_files = {item.name for item in active_path.iterdir()} if active_path.is_dir() else set()
            if any(name in model_files for name in ("inference.json", "inference.pdmodel")):
                kwargs["text_recognition_model_dir"] = str(active_path)
                optional_keys.pop("text_recognition_model_name", None)
                optional_keys.pop("text_recognition_model_dir", None)
        for paddle_key, config_key in optional_keys.items():
            value = self.settings.get(config_key)
            if value:
                kwargs[paddle_key] = value

        try:
            self._pipeline = PaddleOCR(**kwargs)
        except Exception as exc:
            self._load_error = exc
            raise
        return self._pipeline

    def warmup(self) -> None:
        self._load()

    @staticmethod
    def _data_from_result(result: Any) -> dict[str, Any]:
        data = getattr(result, "json", result)
        if callable(data):
            data = data()
        if not isinstance(data, dict):
            return {}
        nested = data.get("res")
        return nested if isinstance(nested, dict) else data

    @staticmethod
    def _prepare_image(image: np.ndarray) -> np.ndarray:
        """Return a contiguous uint8 BGR image accepted by PaddleOCR/PaddleX.

        OpenCV preprocessing commonly produces two-dimensional grayscale arrays.
        PaddleOCR 3.x text detection expects H x W x 3 input and otherwise fails
        while unpacking the image shape. Converting at the engine boundary keeps
        every preprocessing variant valid and also protects future callers.
        """
        array = np.asarray(image)
        if array.size == 0:
            raise ValueError("OCR input image is empty")

        if array.ndim == 2:
            array = np.repeat(array[:, :, np.newaxis], 3, axis=2)
        elif array.ndim == 3:
            channels = array.shape[2]
            if channels == 1:
                array = np.repeat(array, 3, axis=2)
            elif channels == 4:
                # OpenCV image data is BGR(A); PaddleOCR only needs BGR.
                array = array[:, :, :3]
            elif channels != 3:
                raise ValueError(
                    f"Unsupported OCR image channel count: {channels}; expected 1, 3 or 4"
                )
        else:
            raise ValueError(
                f"Unsupported OCR image shape: {array.shape}; expected HxW or HxWxC"
            )

        if array.dtype != np.uint8:
            if np.issubdtype(array.dtype, np.floating):
                array = np.nan_to_num(array, nan=0.0, posinf=255.0, neginf=0.0)
            array = np.clip(array, 0, 255).astype(np.uint8)

        return np.ascontiguousarray(array)

    def recognize_many(
        self,
        images: Sequence[np.ndarray],
        whitelists: Sequence[str | None] | None = None,
    ) -> list[list[OCRToken]]:
        if not images:
            return []
        if whitelists is not None and len(whitelists) != len(images):
            raise ValueError("whitelists must have the same length as images")
        pipeline = self._load()
        prepared_images = [self._prepare_image(image) for image in images]
        results = list(pipeline.predict(prepared_images))
        output: list[list[OCRToken]] = []
        for image_index, result in enumerate(results):
            # PaddleOCR has no runtime API to constrain its trained character
            # dictionary per call (unlike tesseract.py's -c
            # tessedit_char_whitelist=...), so the whitelist is applied
            # post-hoc to the recognized text instead. See
            # apply_character_whitelist()'s docstring for the trade-off.
            whitelist = whitelists[image_index] if whitelists is not None else None
            data = self._data_from_result(result)
            texts = list(data.get("rec_texts", []) or [])
            scores = list(data.get("rec_scores", []) or [])
            boxes = list(data.get("rec_boxes", []) or [])
            tokens: list[OCRToken] = []
            for index, text in enumerate(texts):
                confidence = float(scores[index]) if index < len(scores) else 0.0
                box = None
                if index < len(boxes) and len(boxes[index]) == 4:
                    coords = [int(value) for value in boxes[index]]
                    box = Box(*coords)
                token_text = apply_character_whitelist(str(text), whitelist)
                tokens.append(OCRToken(text=token_text, confidence=confidence, box=box))
            output.append(tokens)

        if len(output) != len(prepared_images):
            raise RuntimeError(
                "PaddleOCR returned "
                f"{len(output)} results for {len(prepared_images)} input images"
            )
        return output

    def info(self) -> dict[str, object]:
        return {
            "provider": "paddleocr",
            "package_version": self._version,
            "ocr_version": self.settings.get("version", "PP-OCRv6"),
            "detection_model": self.settings.get("detection_model"),
            "recognition_model": self.settings.get("recognition_model"),
            "device": self.settings.get("device", "cpu"),
            "inference_engine": self.settings.get("inference_engine", "paddle_static"),
        }
