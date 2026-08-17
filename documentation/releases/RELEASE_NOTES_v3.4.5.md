# IsalaOCR v3.4.5

## Fixed from the captured Windows/Docker diagnostics

- The actual NVIDIA runtime is healthy: PaddlePaddle is CUDA-enabled and one GPU is visible.
- Training then failed before epoch 1 because the legacy vendor image exposed Shapely 1.x, while the pinned PaddleOCR source imports the Shapely 2.x top-level `intersection` API.
- Training image revision `3.3.12` installs and verifies `shapely==2.1.2` in a separate small Docker layer. The existing CUDA, PaddlePaddle and PaddleX dependency layer remains ahead of this change and can be reused from BuildKit cache.
- `paddlex_runner.py` now verifies the Shapely API before PaddleOCR starts and emits a direct repair instruction for stale images.
- The menu no longer calls `ContainsKey()` on a potentially missing action definition, and its catalog/argument dispatch is explicitly null-safe for Windows PowerShell 5.1.
- The launcher removes Mark-of-the-Web from project `.ps1` and `.cmd` files so direct diagnostic runs do not repeatedly show trust prompts.
- The menu header displays the installed project version.

## Required action

Run option 1 once to create `isalaocr-training-cpu:3.3.12` and `isalaocr-training-gpu:3.3.12`. The heavyweight dependency layers should be reused when the Docker BuildKit cache is still present. Then run option 10.

No labels, reviews, DICOMs, datasets, pretrained weights or previous run directories are removed.
