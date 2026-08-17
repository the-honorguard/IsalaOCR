# IsalaOCR v3.3.9 — PaddleOCR repository-API bootstrap

## Fixed

- Fixed GPU training failing with `PP-OCRv6_medium_rec is not a registered model name`.
- Added a bootstrap that locates the local PaddleOCR training repository, sets `PADDLE_PDX_PADDLEOCR_PATH`, disables empty eager repository initialization and explicitly loads the PaddleOCR repository API from the pinned PaddleX 3.7.2 source tree.
- Added preflight validation for `tools/train.py`, the `ppocr` package, model registration and the registered runner root.
- Mounted `training_runtime` read-only into `training-setup`, `trainer-cpu` and `trainer-gpu`, allowing runtime-only repairs without rebuilding the multi-gigabyte training images.
- Kept `TRAINING_IMAGE_VERSION` at `3.3.7`; existing CPU/GPU images and downloaded packages remain reusable.

## Data preservation

No DICOMs, crops, labels, reviews, datasets, model files or prior run directories are deleted or rewritten.
