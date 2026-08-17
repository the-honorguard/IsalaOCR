from __future__ import annotations

import csv
import io
import shutil
import subprocess
import tempfile
from typing import Any, Sequence

import cv2
import numpy as np

from ..models import Box, OCRToken
from .base import OCREngine


class TesseractEngine(OCREngine):
    """Diagnostic fallback. PaddleOCR remains the intended production engine."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        executable = str(settings.get("executable", "tesseract"))
        self.executable = shutil.which(executable) or executable
        if not shutil.which(executable):
            raise RuntimeError(f"Tesseract executable not found: {executable}")

    def _recognize(self, image: np.ndarray, whitelist: str | None) -> list[OCRToken]:
        suffix = ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix) as handle:
            if not cv2.imwrite(handle.name, image):
                raise RuntimeError("Could not write temporary OCR image")
            command = [
                self.executable,
                handle.name,
                "stdout",
                "--psm",
                str(self.settings.get("page_segmentation_mode", 7)),
                "-l",
                str(self.settings.get("language", "eng")),
                "tsv",
            ]
            if whitelist:
                command.extend(["-c", f"tessedit_char_whitelist={whitelist}"])
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=float(self.settings.get("timeout_seconds", 30)),
            )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Tesseract failed")

        tokens: list[OCRToken] = []
        for row in csv.DictReader(io.StringIO(completed.stdout), delimiter="\t"):
            text = (row.get("text") or "").strip()
            if not text:
                continue
            try:
                confidence = max(0.0, float(row.get("conf", "-1")) / 100.0)
                x = int(row["left"])
                y = int(row["top"])
                w = int(row["width"])
                h = int(row["height"])
            except (ValueError, KeyError):
                continue
            tokens.append(OCRToken(text=text, confidence=confidence, box=Box(x, y, x + w, y + h)))
        return tokens

    def recognize_many(
        self,
        images: Sequence[np.ndarray],
        whitelists: Sequence[str | None] | None = None,
    ) -> list[list[OCRToken]]:
        actual_whitelists = whitelists or [None] * len(images)
        if len(actual_whitelists) != len(images):
            raise ValueError("whitelists must have the same length as images")
        return [
            self._recognize(image, whitelist)
            for image, whitelist in zip(images, actual_whitelists, strict=True)
        ]

    def info(self) -> dict[str, object]:
        version = subprocess.run(
            [self.executable, "--version"], capture_output=True, text=True, check=False
        ).stdout.splitlines()
        return {
            "provider": "tesseract",
            "package_version": version[0] if version else "unknown",
            "language": self.settings.get("language", "eng"),
        }
