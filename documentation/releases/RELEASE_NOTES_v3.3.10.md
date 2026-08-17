# IsalaOCR v3.3.11 — non-root PaddleOCR repository access

## Fixed

- Fixed `PermissionError: /root/PaddleOCR` before PaddleX model registration.
- Exposes the vendor image's existing PaddleOCR checkout through `/opt/isala-paddleocr`.
- Grants only traversal (`0711`) on `/root`; directory listing remains unavailable to the application user.
- Verifies during the Docker build that configured UID/GID `10001:10001` can identify the repository and read `tools/train.py`.
- Treats inaccessible discovery candidates as unavailable instead of aborting with a raw `PermissionError`.
- Bumped the reusable CPU/GPU training image revision to `3.3.11`.

## Cache behavior

The new repository-access step is after the heavyweight PaddlePaddle/PaddleX installation layer. Existing CUDA, PaddlePaddle and PaddleX BuildKit layers can therefore be reused; no package redownload is expected while the local Docker cache remains intact.

## Data preservation

No DICOMs, crops, labels, reviews, datasets, model files or prior run directories are deleted or rewritten.
