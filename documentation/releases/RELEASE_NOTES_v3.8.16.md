# IsalaOCR 3.8.16 — configurable localization dataset splits

## Summary

Step 4 now exposes the exact train/validation/test distribution used by the field-detector dataset. Small projects use a safer deterministic automatic split: with 14 completed source images the default is 9 train / 2 validation / 3 test.

## Changes

- Added Train / Validation / Test count controls to Step 4.
- Added per-source Auto / Train / Validation / Test overrides in the dataset preview.
- Automatic split enforces useful hold-out minima for small datasets while remaining deterministic.
- Preview and COCO builder use the same resolver.
- Immutable dataset manifests now persist `source_splits` and `split_policy`.
- Detector evaluation reads split membership from the built dataset manifest instead of recomputing the old 70/15/15 hash buckets.
- Changing split membership creates `localization_split_pending.flag`; detector training is blocked until Step 4 is rebuilt and Step 5 is validated again.
- Successful dataset build clears the pending split marker.
- PowerShell remediation text for localization training now uses ASCII separators to avoid Windows PowerShell 5.1 mojibake.

Heavy training image revision remains 3.8.4.
