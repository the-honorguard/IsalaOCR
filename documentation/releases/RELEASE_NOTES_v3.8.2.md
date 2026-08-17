# IsalaOCR v3.8.2 — Paddle model preparation hotfix

## Fixed

Action 1 could inherit `/models/active-recognition` from `app.yaml` while it was supposed to warm only the shared official OCR cache. If that legacy/custom directory contained a stale or incomplete exported model, PaddleOCR attempted to create the full OCR pipeline with that model and failed before the official cache preparation completed.

Shared model preparation now explicitly removes `active_recognition_model_dir` and `recognition_model_dir` from its effective settings. Runtime OCR still uses the project-specific active model; only action 1 ignores activated/custom recognition models.

PP-StructureV3 is part of the document-parser capability domain in PaddleOCR 3.7. The runtime image now installs `paddleocr[doc-parser]==3.7.0` instead of only the base `paddleocr==3.7.0`, ensuring the required PaddleX OCR/document-parser dependencies are present for table/cell preparation.

Preparation errors now identify whether the failure occurred in the shared OCR pipeline or PP-StructureV3 and include the underlying Paddle error.

## Upgrade

Extract v3.8.2 over v3.8.1 and run `START.cmd`. Action 1 will rebuild the reusable runtime/model-prep dependency layer once because the PaddleOCR dependency set changed. Existing projects, reviews, datasets and models remain untouched.
