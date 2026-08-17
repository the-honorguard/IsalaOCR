# IsalaOCR 3.7.0 — Detection Pipeline Separation

## Architecture

Version 3.7.0 splits the application into two hard stages:

- **Pipeline A — Field Detection & Crop Geometry:** source image -> candidate geometry -> manual review -> localization ground truth -> object-detector training/evaluation -> detection gate.
- **Pipeline B — Value Mapping & OCR:** semantic mapping -> final crops -> value recognition/review -> recognition-model training.

Pipeline B is blocked in both the web UI/job API and PowerShell actions until the detection gate is open.

## Candidate Detection Engine

Pipeline A fuses geometry from OCR/text detection, PP-StructureV3 table/cell detection and the active trained localization model. OCR text from the geometry pass is deliberately discarded rather than stored as value data. Table structure contributes geometry only at this stage.

## Detection Review Studio

Added a dedicated full-image geometry editor with:

- candidate overlays and crop preview;
- drag and 8-handle resize editing;
- numeric x/y/width/height editing;
- Correct, Aangepast and Afgekeurd decisions;
- structured reason categories;
- manual drawing of a completely missed field;
- deletion of manual annotations;
- batch acceptance of pending candidates;
- independently toggleable field-candidate, table-region and table-cell overlays;
- keyboard review/navigation controls.

Review changes invalidate a previously open detection gate.

## Localization data and training

Database schema is now **v11** with dedicated tables for detection candidates, reviews, annotations, table geometry, localization datasets, localization models and localization evaluations. Recognition samples remain separate.

Reviewed source images and bounding boxes are exported to a single-class COCO dataset (`field_roi`). A PaddleX/PaddleDetection localization runtime has been added, preferring PicoDet-S, with separate GPU/CPU training actions.

Evaluation records Recall@IoU>=0.75, precision, mean/median IoU, false positives per image and auto-accept rate. The default gate also requires at least 3 test images and 10 ground-truth ROIs. A passing evaluation does not open the gate by itself: activation is explicit.

## Strict crop ownership

Mapping no longer synthesizes, pads or resizes final crop geometry. A semantic value can only be mapped when it resolves to a reviewed Pipeline-A annotation or a current Pipeline-A candidate; reviewed ground truth is authoritative. This prevents Pipeline-B OCR/mapping heuristics from undoing manual geometry corrections.

## Menu/actions

Pipeline A uses actions 1–13. Pipeline B begins at action 20. Recognition data/training is now 24–28. Legacy queued action IDs 107–116 remain supported for compatibility where applicable.

## Migration

Existing recognition samples, reviews, mapping feedback and models are preserved. After upgrading from 3.6.x, run a new localization cycle and pass the detection gate before using Mapping Studio.
