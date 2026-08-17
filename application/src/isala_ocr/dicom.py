from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np


@dataclass
class DecodedDicom:
    image: np.ndarray
    source_id: str
    safe_metadata: dict[str, Any]


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_uint8(array: np.ndarray) -> np.ndarray:
    values = np.asarray(array)
    if values.dtype == np.uint8:
        return values.copy()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    lower, upper = np.percentile(finite, [0.5, 99.5])
    if upper <= lower:
        lower = float(np.min(finite))
        upper = float(np.max(finite))
    if upper <= lower:
        return np.zeros(values.shape, dtype=np.uint8)
    clipped = np.clip(values.astype(np.float32), lower, upper)
    scaled = (clipped - lower) / (upper - lower) * 255.0
    return np.round(scaled).astype(np.uint8)


def _select_frame(array: np.ndarray, samples_per_pixel: int, strategy: str, index: int) -> np.ndarray:
    if samples_per_pixel == 3:
        if array.ndim == 3:
            return array
        if array.ndim == 4:
            frames = array
        else:
            raise ValueError(f"Unsupported color pixel array shape: {array.shape}")
    else:
        if array.ndim == 2:
            return array
        if array.ndim == 3:
            frames = array
        else:
            raise ValueError(f"Unsupported grayscale pixel array shape: {array.shape}")

    frame_count = len(frames)
    if strategy == "first":
        chosen = 0
    elif strategy == "middle":
        chosen = frame_count // 2
    elif strategy == "index":
        chosen = min(max(index, 0), frame_count - 1)
    elif strategy == "max_contrast":
        scores = [float(np.std(frame)) for frame in frames]
        chosen = int(np.argmax(scores))
    else:
        raise ValueError(f"Unknown frame selection strategy: {strategy}")
    return frames[chosen]


def decode_dicom(path: str | Path, settings: dict[str, Any] | None = None) -> DecodedDicom:
    settings = settings or {}
    source_path = Path(path)
    try:
        import pydicom
        try:
            from pydicom.pixels import apply_voi_lut, convert_color_space
        except ImportError:
            from pydicom.pixel_data_handlers.util import apply_voi_lut, convert_color_space
    except ImportError as exc:
        raise RuntimeError("pydicom is required to decode DICOM files") from exc

    dataset = pydicom.dcmread(str(source_path), force=False)
    if "PixelData" not in dataset:
        raise ValueError("DICOM object contains no PixelData")

    try:
        pixels = dataset.pixel_array
    except Exception as exc:
        raise RuntimeError(
            "Could not decode DICOM PixelData. Install the compressed DICOM extras when required."
        ) from exc

    samples = int(getattr(dataset, "SamplesPerPixel", 1) or 1)
    selected = _select_frame(
        pixels,
        samples_per_pixel=samples,
        strategy=str(settings.get("frame_selection", "first")),
        index=int(settings.get("frame_index", 0)),
    )

    photometric = str(getattr(dataset, "PhotometricInterpretation", ""))
    if samples == 3:
        if photometric.startswith("YBR"):
            selected = convert_color_space(selected, photometric, "RGB")
        rgb = _normalize_uint8(selected)
        image = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    else:
        try:
            selected = apply_voi_lut(selected, dataset)
        except Exception:
            pass
        grayscale = _normalize_uint8(selected)
        if photometric == "MONOCHROME1":
            grayscale = 255 - grayscale
        image = cv2.cvtColor(grayscale, cv2.COLOR_GRAY2BGR)

    safe_metadata = {
        "modality": str(getattr(dataset, "Modality", "")),
        "manufacturer": str(getattr(dataset, "Manufacturer", "")),
        "manufacturer_model_name": str(getattr(dataset, "ManufacturerModelName", "")),
        "rows": int(getattr(dataset, "Rows", image.shape[0]) or image.shape[0]),
        "columns": int(getattr(dataset, "Columns", image.shape[1]) or image.shape[1]),
        "number_of_frames": int(getattr(dataset, "NumberOfFrames", 1) or 1),
        "photometric_interpretation": photometric,
    }
    return DecodedDicom(
        image=image,
        source_id=hash_file(source_path)[:24],
        safe_metadata=safe_metadata,
    )
