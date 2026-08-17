# IsalaOCR 3.10.11

## Smart detector-evaluation pipeline

Stap 5 is rebuilt around a next-action decision pipeline instead of a broad metrics dashboard.

- TRAIN is used first as a learning/sanity check.
- Confidence is calibrated on VALIDATION, never on TEST.
- VALIDATION errors are automatically classified into near-match/localization, duplicates, unmatched false positives, negative regions and false negatives.
- A rule-based Model Improvement Assistant selects one primary root cause and one concrete next action.
- The hold-out TEST is skipped while VALIDATION cannot produce a production-confidence.
- When VALIDATION is ready, Step 5 runs one final TEST at the locked validation-selected confidence. TEST is not used for retuning.
- Visual diagnostics default to VALIDATION and support split, confidence, diagnostic IoU and FP-cause filters.
- Raw metrics and threshold tables remain available under Geavanceerde diagnostiek.
- Metric definitions are available directly in the UI.
- Step 5 now resolves the selected detector from `evaluation_model_id` plus its run registration, so it cannot silently fall back to baseline-only because the persisted selection lacks an embedded model object.

No detector retraining is required to install this version. A new evaluation is required to generate the new improvement-pipeline metadata for an existing model.
