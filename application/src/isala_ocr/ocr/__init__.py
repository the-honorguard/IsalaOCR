from __future__ import annotations

from typing import Any

from .base import OCREngine
from .paddle import PaddleEngine
from .recognition import PaddleRecognitionEngine
from .tesseract import TesseractEngine


def create_engine(settings: dict[str, Any], override: str | None = None) -> OCREngine:
    provider = (override or settings.get("provider", "paddle")).lower()
    if provider == "paddle":
        return PaddleEngine(settings)
    if provider in {"paddle-recognition", "paddle_recognition"}:
        return PaddleRecognitionEngine(settings)
    if provider == "tesseract":
        return TesseractEngine(settings.get("tesseract", settings))
    raise ValueError(f"Unsupported OCR provider: {provider}")


__all__ = [
    "OCREngine",
    "PaddleEngine",
    "PaddleRecognitionEngine",
    "TesseractEngine",
    "create_engine",
]
