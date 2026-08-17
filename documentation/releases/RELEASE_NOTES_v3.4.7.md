# IsalaOCR v3.4.7

## NumPy pickle compatibility for official pretrained weights

The official `PP-OCRv6_medium_rec_pretrained.pdparams` can contain pickle references to `numpy._core.multiarray`, the module path emitted by NumPy 2. The reusable training image can legitimately use NumPy 1.x, where the equivalent implementation is exposed as `numpy.core.multiarray`.

This release adds a narrowly scoped runtime compatibility layer that:

- maps the NumPy 2 pickle module names to their NumPy 1.x equivalents only when native `numpy._core` is absent;
- propagates the compatibility startup module to the PaddleX bootstrap and the separate PaddleOCR `tools/train.py` subprocess;
- verifies `numpy._core.multiarray._reconstruct` before training, evaluation and export;
- does not upgrade or replace NumPy, PaddlePaddle, CUDA, Shapely or the existing training images.

The training image revision remains `3.3.12`. Option 1 is not required after installing this release.
