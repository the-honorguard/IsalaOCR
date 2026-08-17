# IsalaOCR 3.8.18 — merged localization training workbench

This release combines localization dataset build, validation and field-detector training on one workflow page.

## Fixed

- Successful PaddleX validation markers from v3.8.15-v3.8.17 used `status: ok`, while the PowerShell training preflight incorrectly checked only a non-existent boolean `ok` field. The preflight now accepts both marker formats.
- New PaddleX validation markers contain both `status: ok` and `ok: true` for explicit compatibility.

## Workflow

- Step 4 is now **Dataset & detector trainen** with three visible phases: build, validate and train.
- Training buttons remain disabled until IsalaOCR validation, PaddleX validation and the current split configuration are all valid.
- Old localization validation/training page URLs redirect to Step 4.
- Subsequent workflow steps are renumbered contiguously; action IDs and queued task compatibility are unchanged.

`TRAINING_IMAGE_VERSION` remains 3.8.4.
