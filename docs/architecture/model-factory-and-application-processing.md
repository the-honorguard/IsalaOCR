# IsalaOCR architecture: Model Factory vs Application Processing

## Primary product: a model bundle

The training workflow exists to produce reusable OCR model artifacts. It must not
require knowledge of one report type, one output JSON schema or application field
names such as `heart_rate` or `lv_ejection_fraction`.

The primary workflow is the **Model Factory**:

1. prepare runtimes/models;
2. define panels/regions used for training data;
3. create and maintain canonical Ground Truth;
4. build/train/evaluate the geometry detector;
5. iterate detector vs canonical GT until the GT/model is sufficient;
6. export/version the trained model bundle.

A model bundle may contain multiple technical artifacts (for example a geometry
model and a recognition model), but the bundle itself remains application-neutral.
Recommended manifest contents are model versions, preprocessing requirements,
class/dictionary metadata, evaluation metrics and runtime compatibility.

## Optional phase 2: Application Processing

Turning raw OCR output into domain/application output is a separate concern and is
not a model-training prerequisite. Existing Mapping Studio work is deliberately
preserved for this later phase.

Application Processing may use:

- functional field schemas;
- aliases and keywords;
- unit hints;
- context/table/panel hints;
- missing-value markers such as `-`, `–` and `—`;
- lateral/context disambiguation;
- transformations and validation rules;
- structured output schemas.

Example:

```text
model output: HR -> 79 bpm
application profile: HR alias + bpm unit -> heart_rate
structured output: {"heart_rate": 79}
```

None of `HR`, `bpm` or `heart_rate` needs to be taught to the model factory as an
application rule. They belong to the selected application profile.

## Compatibility policy

The Mapping Studio, mapping database, fullscreen reviewer, relation feedback,
canonical-GT mapping build and schema-scoring code are retained. During the
transition, historical modules under `isala_ocr.training.mapping*` remain valid so
existing jobs/routes do not break.

Application-only semantic helpers now live under:

`isala_ocr.application_processing`

The old `training.mapping_semantics` and `training.mapping_lateral` modules are
compatibility shims. Additional mapping code can be migrated incrementally later
without deleting the already-built workflow.

## Boundary rule

A feature belongs in **training/model factory** only when it affects how model
artifacts or their training/evaluation data are produced.

A feature belongs in **application processing** when it changes how already-read
OCR content is interpreted, named, validated or serialized for a downstream use
case.
