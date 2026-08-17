from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def _upscale(image: np.ndarray, factor: float, interpolation: int = cv2.INTER_CUBIC) -> np.ndarray:
    if factor <= 1:
        return image
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interpolation)


def make_variants(
    crop: np.ndarray,
    variant_names: Iterable[str],
    upscale_factor: float = 4.0,
) -> list[tuple[str, np.ndarray]]:
    gray = _gray(crop)
    outputs: list[tuple[str, np.ndarray]] = []
    for name in variant_names:
        if name == "original_upscale":
            value = _upscale(crop, upscale_factor)
        elif name == "grayscale_upscale":
            value = _upscale(gray, upscale_factor)
        elif name == "clahe_upscale":
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            value = _upscale(clahe.apply(gray), upscale_factor)
        elif name == "binary_inverted":
            inverted = 255 - gray
            _, value = cv2.threshold(inverted, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            value = _upscale(value, upscale_factor)
        elif name == "inverted_lanczos":
            value = _upscale(255 - gray, upscale_factor, cv2.INTER_LANCZOS4)
        elif name == "clahe_lanczos":
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            value = _upscale(clahe.apply(gray), upscale_factor, cv2.INTER_LANCZOS4)
        elif name == "adaptive_inverted":
            inverted = 255 - gray
            value = cv2.adaptiveThreshold(
                inverted,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                21,
                5,
            )
            value = _upscale(value, upscale_factor)
        else:
            raise ValueError(f"Unknown preprocessing variant: {name}")
        outputs.append((name, value))
    return outputs
