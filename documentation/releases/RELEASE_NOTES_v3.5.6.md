# IsalaOCR 3.5.6

## Self-healing OCR model selection

Crop collection no longer forces `PP-OCRv6_small_rec` when an activated custom model is present. The runtime reads the actual model family from the activated model's `inference.yml`/JSON metadata and supplies that matching name to PaddleX. This prevents a fine-tuned `PP-OCRv6_medium_rec` model from being rejected by a stale small-model default.

## Safe housekeeping

Before crop collection, IsalaOCR removes only interrupted-write artifacts:

- `models/active-recognition.new`;
- `*.part`, `*.partial`, and temporary files under model storage;
- temporary web-job files.

DICOM input, crops, reviews, datasets, runs, registered models, and the active model are never removed by automatic housekeeping.

## Collection defaults

The collection script now uses model mode `auto`. An explicit model can still be supplied, but normal web and menu runs automatically use the valid activated model or the configured official fallback.
