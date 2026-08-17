# IsalaOCR 3.8.19 — canonical localization readiness

This release removes ambiguity between the dataset shown in Step 4 and the dataset checked by detector-training preflight.

- `localization_datasets/latest.txt` is now the canonical current localization dataset everywhere.
- IsalaOCR validation must match the exact current dataset ID.
- PaddleX validation must point at the exact same dataset ID.
- A successful two-stage validation writes `training_ready.json`, bound to that immutable dataset and its manifest hash.
- Starting a new validation removes the old readiness marker until both checks pass again.
- Training preflight reports the exact dataset ID and all readiness flags.
- The Step 4 UI exposes the current dataset ID and the canonical readiness marker.

Heavy training images remain at revision 3.8.4.
