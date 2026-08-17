from __future__ import annotations

from pathlib import Path

import cv2

from .dicom import DecodedDicom, hash_file


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def load_input(path: str | Path, dicom_settings: dict | None = None) -> DecodedDicom:
    source = Path(path)
    if source.suffix.lower() in IMAGE_EXTENSIONS:
        image = cv2.imread(str(source), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not read image: {source}")
        return DecodedDicom(
            image=image,
            source_id=hash_file(source)[:24],
            safe_metadata={"input_type": "image"},
        )

    from .dicom import decode_dicom

    return decode_dicom(source, dicom_settings)
