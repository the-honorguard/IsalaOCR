# Value Mapping & OCR — Pipeline B

## Boundary

Since v3.7.0, Mapping Studio is **not** part of field detection. Pipeline A must first produce reliable crop geometry, train/evaluate the field-localization detector and open the detection quality gate. Pipeline B is unavailable while that gate is closed.

The separation is deliberate:

1. Pipeline A determines **where** the crop is and owns its bounding box.
2. Pipeline B determines **what the crop means** and **what text/value it contains**.

Pipeline B may use semantic OCR/table information, but it may not synthesize, pad or silently resize final ROI geometry.

## Step 20 — Mapping Studio

After the gate opens, semantic OCR/table interpretation is generated for the source and proposed label/value relations are shown. The user maps a relation to an editable functional field definition.

A relation is eligible for confirmation only when its value can be resolved to Pipeline-A geometry. The studio shows this explicitly and previews:

- the source image with the authoritative crop box;
- detected label/value context;
- the selected functional field;
- expected structured JSON;
- Pipeline-A geometry provenance and match score.

Reviewed Pipeline-A annotations are authoritative. If an explicitly corrected annotation matches the semantic value, a newer machine candidate cannot override it.

Mapping relation feedback remains supported: confirmed relations are positive mapping examples and explicitly rejected relations are negative mapping examples with a structured reason. This feedback improves relation proposals; it does not alter Pipeline-A crop geometry.

## Step 21 — Apply confirmed mappings / create final crops

Each confirmed functional mapping is materialized using the authoritative Pipeline-A ROI. The crop is marked as awaiting value recognition. If a mapping or its geometry changes, the previous mapped sample becomes stale and is excluded from active value/recognition training flows until rematerialized.

No value OCR is run in this step.

## Step 22 — Read values

Recognition runs only on final mapped crops that satisfy the ROI/review eligibility rules. The exact OCR string is preserved. Parsing and validation are stored separately, for example:

```json
{
  "raw_text": "106,8 ml",
  "parsed_value": 106.8,
  "parsed_unit": "ml",
  "parse_status": "ok",
  "range_valid": true
}
```

## Step 23 — Review values

This screen assesses only OCR content. Crop geometry corrections belong in Detection Review Studio; semantic mapping corrections belong in Mapping Studio.

## Steps 24–28 — Recognition training

Recognition datasets remain crop -> exact text datasets and are completely separate from the full-image localization COCO dataset:

- 24 build recognition dataset;
- 25 validate recognition dataset;
- 26 train recognition model;
- 27 evaluate/compare recognition model;
- 28 register/activate recognition model.

## Functional field schema

Functional fields remain editable data, not hardcoded detector classes. Definitions can include field key, display/group name, datatype, preferred unit, aliases, range rules and required/optional state. The detector remains generic because Pipeline A has only the class `field_roi`.

## Storage separation

Pipeline B continues to use semantic/mapping/value entities such as:

- `detected_blocks` and `detected_relations` for semantic interpretation;
- `field_definitions`, `field_mappings` and `mapping_profiles`;
- `mapping_relation_feedback`;
- `samples` and exact labels for value recognition/review.

These are intentionally separate from Pipeline-A `detection_candidates`, `detection_reviews`, `detection_annotations`, localization datasets/models/evaluations and table-geometry records.

## Privacy

Processing remains local. Source identifiers are derived and training output does not intentionally include original DICOM identifiers or source filenames. The local web interface is bound to loopback by default.
