# IsalaOCR v3.3.11

## Fixed

- Replaced the incorrect assumption that the PaddleX vendor base image contains a complete PaddleOCR training repository.
- Downloads the immutable PaddleOCR source revision `b03f46425e8ff4442b268ce449e3eef758146cd4` during reusable training-image preparation.
- Caches the PaddleOCR source archive in BuildKit so subsequent builds do not redownload it.
- Installs the repository at `/opt/isala-paddleocr`, owned by runtime UID/GID `10001:10001`.
- Verifies `tools/train.py`, the `ppocr` package and a PP-OCRv6 medium recognition configuration before completing the image.
- Keeps the large CUDA, PaddlePaddle and PaddleX layers before this source layer so those downloads remain cacheable.

## Data safety

No datasets, reviews, crops, labels, models or previous run directories are changed.
