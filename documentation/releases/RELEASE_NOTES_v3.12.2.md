# IsalaOCR 3.12.2

## Table-cell training validation hotfix

The new wireless table-cell fine-tuning loop could train normally but fail at its first inline COCO validation pass because PaddleDetection writes `bbox.json` as a relative path from its root-owned source checkout. The IsalaOCR trainer runs as UID/GID 10001, so that location is intentionally not writable.

v3.12.2 routes only PaddleDetection's known relative evaluation artifacts (`bbox.json`, `mask.json`, `segm.json`, `keypoint.json`) into `<table-cell-run>/evaluation_artifacts/`. The existing non-root container model and all dataset/model mounts remain unchanged.

No model is activated automatically. Re-run the same table-cell training action after upgrading; the validated dataset can be reused.
