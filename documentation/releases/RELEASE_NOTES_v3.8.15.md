# IsalaOCR 3.8.15 — PaddleX COCO path compatibility

## Fixed

Localization datasets generated through 3.8.14 stored COCO image records as `images/<file>.png`. IsalaOCR's own validator accepted those paths because it resolved them from the dataset root, but PaddleX COCODetDataset resolves every image as `dataset_dir/images/<file_name>`. The old JSON therefore caused PaddleX to search for `images/images/<file>.png` after pycocotools had already loaded the annotations successfully.

3.8.15 writes the COCO `file_name` as the basename relative to the dataset image directory and validates against PaddleX's exact resolution rules. Existing 3.8.14 localization datasets are intentionally not mutated: rebuild Step 4 once to create a corrected immutable dataset.

## Diagnostics

The PaddleX validation/training runtime now performs a fast compatibility preflight and reports the exact missing path. If PaddleX itself still rejects a dataset, `check_dataset_result.json` is printed when available rather than returning only the generic `PaddleX rejected the localization dataset` message.

## Upgrade impact

- Re-run **Step 4 · Localization-dataset bouwen** after upgrading.
- Then re-run localization dataset validation.
- `TRAINING_IMAGE_VERSION` remains **3.8.4**; no large CPU/GPU training-image rebuild is required.
