# IsalaOCR 3.8.14 — Read-only localization dataset builder fix

## Localization workspace isolation

Localization-only CLI commands no longer initialize or create the project-specific active recognition-model directory under `/models/projects/<project>/active-recognition`. Dataset build and validation run in the intentionally read-only `dataset-builder` container and only need the project training workspace.

This fixes the COCO localization dataset build failure where `_training_workspace()` attempted to create `/models/projects/...` even though `/models` is part of the read-only container filesystem. Recognition-aware commands keep the existing project-specific active-recognition setup.

The same read-only workspace path is now used consistently for localization dataset build/validation, localization evaluation/comparison, prediction merge/evaluation, model registration and detection-quality reporting.

This is an application/CLI fix. `TRAINING_IMAGE_VERSION` remains **3.8.4**.
