# IsalaOCR 3.10.3

This maintenance release fixes a false-negative Docker image check in Step 1 preparation.

## Preparation reliability

- Docker image detection is centralized in `training-common.ps1`.
- `prepare-training.ps1` and `preparation-status.ps1` now use the same timeout-aware image-inspection helper.
- A valid `sha256:` ID returned by `docker image inspect` is accepted even if Windows PowerShell 5.1 momentarily fails to expose the native process exit code.
- Newly exported CPU/GPU training images are inspected with short retries before being declared missing.
- Download readiness is unchanged: existing model files and base images are not downloaded again merely because an install validation failed.

## Verification

- Regression tests cover centralized image inspection and post-build retry behavior.
