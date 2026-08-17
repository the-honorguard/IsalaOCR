from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..models import OCRToken
from .base import OCREngine
from .paddle import PaddleEngine
from .paddlex_runtime import prepare_paddlex_runtime


class PaddleRecognitionEngine(OCREngine):
    """Recognition-only wrapper for already cropped text lines.

    Unlike :class:`PaddleEngine`, this module does not run text detection. It is
    therefore the preferred engine for fixed, tightly calibrated field ROIs and
    for baseline/custom-model evaluation.
    """

    def __init__(self, settings: dict[str, Any], model_dir: str | Path | None = None):
        self.settings = dict(settings)
        self.explicit_model_dir = Path(model_dir) if model_dir else None
        self._model = None
        self._version = "unknown"
        self._resolved_model_dir: str | None = None
        self._load_error: Exception | None = None

    @staticmethod
    def _usable_model_dir(path: Path | None) -> bool:
        if not path or not path.is_dir():
            return False
        required_any = {"inference.json", "inference.pdmodel", "model.safetensors"}
        names = {item.name for item in path.iterdir() if item.is_file()}
        return bool(required_any & names) and any(
            name.endswith((".pdiparams", ".safetensors")) for name in names
        )


    @staticmethod
    def _find_model_name(value: Any) -> str | None:
        """Recursively find the PaddleOCR model family recorded in model metadata."""
        if isinstance(value, str) and value.startswith("PP-OCR") and value.endswith("_rec"):
            return value
        if isinstance(value, dict):
            preferred = ("model_name", "ModelName", "model", "architecture")
            for key in preferred:
                if key in value:
                    found = PaddleRecognitionEngine._find_model_name(value[key])
                    if found:
                        return found
            for item in value.values():
                found = PaddleRecognitionEngine._find_model_name(item)
                if found:
                    return found
        if isinstance(value, (list, tuple)):
            for item in value:
                found = PaddleRecognitionEngine._find_model_name(item)
                if found:
                    return found
        return None

    @classmethod
    def _model_name_from_dir(cls, path: Path | None) -> str | None:
        """Read the real model family from an exported/activated model directory.

        PaddleX validates ``model_name`` against the model's inference metadata.
        Activated fine-tuned models can therefore not safely inherit the default
        ``PP-OCRv6_small_rec`` value from app.yaml.
        """
        if not path or not path.is_dir():
            return None
        for candidate in (path / "isala_model.json", path / "model.json", path / "inference.json"):
            if not candidate.is_file():
                continue
            try:
                found = cls._find_model_name(json.loads(candidate.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, TypeError):
                found = None
            if found:
                return found
        yaml_path = path / "inference.yml"
        if yaml_path.is_file():
            try:
                import yaml
                found = cls._find_model_name(yaml.safe_load(yaml_path.read_text(encoding="utf-8-sig")))
            except (ImportError, OSError, ValueError, TypeError):
                found = None
            if found:
                return found
        return None

    def _official_cache_model_dir(self) -> Path:
        model_root = Path(str(self.settings.get("model_root", "/models/paddlex")))
        model_name = str(
            self.settings.get("recognition_model", "PP-OCRv6_small_rec")
        )
        return model_root / "official_models" / model_name

    def _select_model_dir(self) -> Path | None:
        if self._usable_model_dir(self.explicit_model_dir):
            return self.explicit_model_dir
        active = self.settings.get("active_recognition_model_dir")
        if active:
            candidate = Path(str(active))
            if self._usable_model_dir(candidate):
                return candidate
        configured = self.settings.get("recognition_model_dir")
        if configured:
            candidate = Path(str(configured))
            if self._usable_model_dir(candidate):
                return candidate
        official_cache = self._official_cache_model_dir()
        if self._usable_model_dir(official_cache):
            return official_cache
        return None

    def _load(self):
        if self._model is not None:
            return self._model
        if self._load_error is not None:
            raise RuntimeError("PaddleOCR recognition initialization previously failed in this process") from self._load_error

        prepare_paddlex_runtime(self.settings)
        selected_dir = self._select_model_dir()
        configured_model_name = str(
            self.settings.get("recognition_model", "PP-OCRv6_small_rec")
        )
        model_name = self._model_name_from_dir(selected_dir) or configured_model_name
        if selected_dir is None and not bool(self.settings.get("allow_downloads", False)):
            expected = self._official_cache_model_dir()
            error = RuntimeError(
                f"Offline recognition model is missing: {model_name}. "
                f"Expected local model files under {expected}. "
                "Run menu option 1 to prepare inference models before baseline evaluation."
            )
            self._load_error = error
            raise error

        try:
            import paddleocr
            from paddleocr import TextRecognition
        except ImportError as exc:
            self._load_error = exc
            raise RuntimeError(
                "PaddleOCR TextRecognition is unavailable. Install the project with the paddle extra."
            ) from exc
        except Exception as exc:
            self._load_error = exc
            raise

        self._version = getattr(paddleocr, "__version__", "unknown")

        kwargs: dict[str, Any] = {
            "device": str(self.settings.get("device", "cpu")),
            "engine": self.settings.get("inference_engine", "paddle_static"),
            "cpu_threads": int(self.settings.get("cpu_threads", 8)),
            "enable_mkldnn": bool(self.settings.get("enable_mkldnn", True)),
        }
        if selected_dir:
            kwargs["model_dir"] = str(selected_dir)
            # PaddleX validates a supplied directory against its recorded model
            # family. Passing the inferred family prevents a stale app.yaml
            # default from rejecting an activated fine-tuned medium model.
            kwargs["model_name"] = model_name
            self._resolved_model_dir = str(selected_dir)
        else:
            kwargs["model_name"] = model_name
        try:
            self._model = TextRecognition(**kwargs)
        except Exception as exc:
            self._load_error = exc
            raise
        return self._model

    def warmup(self) -> None:
        self._load()

    @staticmethod
    def _result_data(result: Any) -> dict[str, Any]:
        data = getattr(result, "json", result)
        if callable(data):
            data = data()
        if not isinstance(data, dict):
            return {}
        nested = data.get("res")
        return nested if isinstance(nested, dict) else data

    def recognize_many(
        self,
        images: Sequence[np.ndarray],
        whitelists: Sequence[str | None] | None = None,
    ) -> list[list[OCRToken]]:
        del whitelists
        if not images:
            return []
        prepared = [PaddleEngine._prepare_image(image) for image in images]
        model = self._load()
        batch_size = int(self.settings.get("recognition_batch_size", 16))
        try:
            results = list(model.predict(input=prepared, batch_size=batch_size))
        except TypeError:
            results = list(model.predict(prepared, batch_size=batch_size))
        output: list[list[OCRToken]] = []
        for result in results:
            data = self._result_data(result)
            text = data.get("rec_text", data.get("text", ""))
            score = data.get("rec_score", data.get("score", 0.0))
            output.append(
                [OCRToken(text=str(text), confidence=float(score or 0.0))]
                if str(text)
                else []
            )
        if len(output) != len(prepared):
            raise RuntimeError(
                f"TextRecognition returned {len(output)} results for {len(prepared)} inputs"
            )
        return output

    def info(self) -> dict[str, object]:
        return {
            "provider": "paddleocr_text_recognition",
            "package_version": self._version,
            "recognition_model": (
                self._model_name_from_dir(Path(self._resolved_model_dir))
                if self._resolved_model_dir
                else self.settings.get("recognition_model")
            ),
            "model_dir": self._resolved_model_dir,
            "device": self.settings.get("device", "cpu"),
            "inference_engine": self.settings.get("inference_engine", "paddle_static"),
        }
