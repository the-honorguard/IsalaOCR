# Architecture – IsalaOCR v3.8.4

## Design objectives

1. Keep pixel data, OCR inference, training data and models local.
2. Separate **field localization** from **semantic mapping/value recognition**.
3. Make geometry reviewable and editable before any value workflow starts.
4. Learn crop geometry from full-image bounding-box annotations instead of recognition labels.
5. Keep table/layout models as candidate-geometry sources rather than semantic truth.
6. Make reviewed human geometry authoritative over machine proposals.
7. Fail closed at the Detection Gate when localization quality is not demonstrated.
8. Avoid patient identifiers in logs and generated filenames.
9. Keep the platform generic while isolating use-case-specific data and models in projects.

## Project and use-case boundary

A **use-case template** describes defaults/intent (for example `philips_cmr_volume_results`). A **project** is the concrete isolated workspace used to collect/review data and train/activate models. The same use-case can therefore have multiple independent experiments.

Project state is stored below `training/workspace/projects/<project-id>`. Recognition registries live below `training/registry/projects/<project-id>` and active recognition models below `models/projects/<project-id>/active-recognition`. New projects also receive a dedicated input subpath by default. The raw input mount, Paddle/PaddleX model cache, Docker images and worker infrastructure remain shared platform resources.

Queued worker jobs carry `project_id` and export it as `ISALA_PROJECT_ID` before invoking PowerShell/Docker. This pins execution to the project in which the job was created even if the user switches projects while it is queued/running.

## Two-pipeline boundary

### Pipeline A – Field Detection & Crop Geometry

Pipeline A answers only: **where are potentially useful fields/crops?**

```text
source image
  -> text/layout geometry
  -> PP-Structure table/cell geometry
  -> active field-detector geometry (optional)
  -> candidate fusion / deduplication
  -> Detection Review Studio
  -> reviewed localization ground truth
  -> COCO localization dataset
  -> object-detector training/evaluation
  -> explicit activation
  -> Detection Gate
```

Pipeline A does not assign a `field_key`, does not persist exact recognized values as localization truth, and does not generate measurement output.

### Pipeline B – Value Mapping & OCR

Pipeline B is unavailable while the Detection Gate is closed.

```text
approved Pipeline-A geometry
  -> semantic OCR / table interpretation
  -> Mapping Studio
  -> confirmed field mapping
  -> final crop from Pipeline-A geometry
  -> ROI review
  -> value recognition
  -> value review
  -> recognition dataset/training/evaluation
  -> structured output
```

Semantic mapping may explain what a region means, but it may not silently invent a new final crop.

## Input and DICOM decoding

`isala_ocr.image_io` accepts ordinary images and DICOM files. `isala_ocr.dicom` uses pydicom, applies VOI LUT where available, handles MONOCHROME1 inversion and converts supported color spaces. Compressed transfer syntaxes use the optional pylibjpeg plugins.

The decoder returns an image, a SHA-256-derived source ID and an allowlisted metadata subset. PatientName, PatientID, accession number and DICOM UIDs are intentionally excluded from generated training identifiers/logging.

## Candidate Detection Engine

`training.localization` represents neutral `LocalizationCandidate` objects. Candidate inputs can include:

- OCR/text detector boxes, while discarding recognized text for localization truth;
- PP-StructureV3 table regions and table cells;
- predictions from the active trained field-detector model.

Fusion/deduplication combines strongly overlapping candidates and retains provenance/confidence. Table regions/cells are also stored separately for diagnostic overlays.

The purpose of PP-Structure in Pipeline A is geometric: **table/cell boundaries**, not label/value semantics. The semantic table layer remains in Pipeline B.

## Detection Review Studio

The Detection Review Studio operates on full source images and `detection_candidates`, not recognition samples. A reviewer can:

- accept a candidate unchanged;
- move/resize it and store corrected coordinates;
- reject a false positive;
- manually draw a completely missed field;
- inspect field/table/table-cell overlays independently.

Explicit positive reviews are stored as `detection_annotations` with training role `positive`; explicit rejection or *not needed for this project* is stored with role `negative`. Unreviewed candidates have no training annotation. Structured reason codes are optional failure-analysis metadata and are not model targets.

If later re-detection no longer produces the original candidate, reviewed ground truth remains persistent. When both a reviewed annotation and a fresh machine candidate overlap, the reviewed annotation is authoritative.

Any ground-truth change closes the Detection Gate until a newly evaluated trained model is explicitly activated.

## Localization dataset

`training.localization_dataset` uses a source-level completion gate. Only source images explicitly marked **Afbeelding klaar** are exported to COCO object-detection format; incomplete sources are excluded entirely, regardless of any individual ROI decisions already stored. Eligible sources are exported as complete full-screen supervision using positive/adjusted/manual boxes as `field_roi` annotations, while Not relevant and Incorrect regions contribute negative/background context. The dataset-preview UI uses the same eligibility rule and deterministic source split as the builder.

The first task intentionally uses a single class:

```text
field_roi
```

This keeps localization generic: the detector learns useful crop geometry without needing to know whether a crop is HR, BSA, ED Volume or another future field.

Train/validation/test assignment is deterministic per `source_id`, preventing source leakage. Explicitly reviewed negative patches/full sources can remain as negative images. Unreviewed candidates are excluded.

## Localization model lifecycle

The localization runtime uses PaddleX/PaddleDetection with `PicoDet-S` as the default model. Preparation, validation, GPU/CPU training, prediction, evaluation and activation are separate actions.

Evaluation is geometric and records:

- Recall at IoU >= 0.75;
- precision;
- mean/median matched IoU;
- false positives per image;
- auto-accept rate at IoU >= 0.90;
- independent test-image and ground-truth counts.

A passing evaluation does not itself open the gate. Activation checks the trained evaluation against the configured thresholds and opens the gate only on success. There is no force bypass.

## Detection Gate

The gate state is stored in the training database. It is enforced at multiple boundaries:

- web navigation/actions;
- queued job submission/retry;
- PowerShell workflow;
- Pipeline-B CLI commands.

This is deliberate defense in depth: a stale UI or direct command must not resume mapping/recognition while localization is unqualified.

## Semantic mapping and final ROI ownership

`training.generic_detection`, semantic parts of `ocr.table_structure` and `training.mapping` belong to Pipeline B.

Mapping can use OCR text, aliases, table row/column context, units and learned relation feedback to propose a functional field. However, `resolve_value_roi_box()` accepts only geometry supplied by Pipeline A:

1. best matching reviewed detection annotation, if present;
2. otherwise a current eligible localization candidate.

Pipeline B cannot pad, resize or synthesize an authoritative final ROI. If no Pipeline-A geometry exists, mapping/crop materialization fails visibly.

## Recognition pipeline

Once a mapping has a valid final crop and that crop is approved, recognition uses the existing OCR abstraction:

- `PaddleEngine` for the normal PaddleOCR path;
- `TesseractEngine` as diagnostic fallback where configured.

Recognition labels remain literal for model training. Parsing, unit interpretation, range validation and cross-field consistency checks operate after raw recognition and remain separate from localization.

The recognition dataset remains a crop-image -> exact-transcription dataset and is never mixed with COCO localization data.

## Study information and output

Study information such as heart rate, BSA, BSA method, height, weight and gender belongs to Pipeline B/output semantics. Raw OCR may be retained there for review, but it is not used as localization truth.

Normal output remains structured under a SHA-256-derived source identifier and follows `application/schemas/result.schema.json` where applicable.

## Database separation

Schema v12 keeps localization-specific state separate and adds explicit relevance/training-role metadata:

```text
detection_sources
detection_candidates
detection_reviews
detection_annotations
detection_table_regions
detection_table_cells
localization_datasets
localization_models
localization_evaluations
```

Existing mapping, sample, review and recognition dataset/run entities remain for Pipeline B. Each project has its own SQLite database/workspace, so project isolation is physical/logical rather than implemented by sharing one database with `project_id` columns. Recognition registry/active-model state is namespaced separately per project.

## Runtime isolation

Model-preparation services may have network access to materialize approved dependencies/models. Runtime collection, dataset work, training/evaluation and normal OCR are designed to run locally after preparation. The review web UI binds to localhost according to the existing configuration and remains lightweight; Paddle/OpenCV-heavy work stays worker-side rather than being imported into the labeler container.

## Web interface migration (3.9.x)

The web layer is being migrated incrementally rather than rewritten as a single release. Python remains the source of truth for projects, datasets, review state, job submission and training readiness. Reactive clients consume explicit JSON contracts and receive change invalidations through Server-Sent Events.

In 3.9.1 **Step 4 · Dataset & detector training** and the detector-quality workflow use React/TypeScript clients. Step 4 reads `/api/v2/localization/workbench`; detector quality reads `/api/v2/localization/quality`. Both submit jobs through `/api/v2/jobs` and listen to `/api/v2/events`. An SSE event does not carry complete application state; it invalidates the owning client so only its small canonical REST resource is refetched. This prevents page reloads and avoids duplicating domain logic in JavaScript.

Detector-quality evaluations store a SHA-256 fingerprint of the reviewed geometry and immutable split scope. Activation is allowed only when the evaluation fingerprint still matches the current source-level ground truth and the hard gate metrics pass.

The compiled browser asset is stored with the Python package and served by the existing labeler service. Node.js is a development/build dependency only, not a runtime service. Legacy Jinja screens and the shared activity dock coexist with the new client until they are migrated in later 3.9.x releases.
