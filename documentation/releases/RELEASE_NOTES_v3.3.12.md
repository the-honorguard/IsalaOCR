# IsalaOCR v3.3.12 — tolerate legacy pretrained-cache permissions

- Keeps reusable CPU/GPU training image revision `3.3.11`; no heavyweight rebuild is required.
- Treats `training_prepare_manifest.json` as optional diagnostic metadata.
- A cached, readable `PP-OCRv6_medium_rec_pretrained.pdparams` now counts as successful preparation even when an older root-created Windows bind-mount directory blocks the non-root container from writing the manifest.
- Training data, reviews, datasets, model weights and previous runs are unchanged.
