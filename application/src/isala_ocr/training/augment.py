from __future__ import annotations

import hashlib

import cv2
import numpy as np


def _rng(seed_text: str) -> np.random.Generator:
    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:8], "big")
    return np.random.default_rng(seed)


def safe_augment(image: np.ndarray, seed_text: str) -> np.ndarray:
    """Apply mild, label-preserving augmentation suitable for tiny numeric OCR crops."""
    rng = _rng(seed_text)
    output = image.astype(np.float32)

    contrast = float(rng.uniform(0.92, 1.08))
    brightness = float(rng.uniform(-8.0, 8.0))
    output = output * contrast + brightness

    if rng.random() < 0.45:
        sigma = float(rng.uniform(0.15, 0.55))
        output = cv2.GaussianBlur(output, (3, 3), sigmaX=sigma)

    if rng.random() < 0.65:
        noise_sigma = float(rng.uniform(0.4, 2.2))
        output += rng.normal(0.0, noise_sigma, size=output.shape)

    output = np.clip(output, 0, 255).astype(np.uint8)

    # At most one pixel of translation; border replication avoids deleting glyphs.
    if output.shape[0] >= 8 and output.shape[1] >= 16 and rng.random() < 0.5:
        tx = int(rng.integers(-1, 2))
        ty = int(rng.integers(-1, 2))
        matrix = np.float32([[1, 0, tx], [0, 1, ty]])
        output = cv2.warpAffine(
            output,
            matrix,
            (output.shape[1], output.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    return output
