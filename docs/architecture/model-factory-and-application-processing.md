# IsalaOCR architecture: Model Factory vs Application Processing

## Primary product: a model bundle

The training workflow exists to produce reusable OCR model artifacts. It must not
require knowledge of one report type, one output JSON schema or application field
names such as `heart_rate` or `lv_ejection_fraction`.

The primary workflow is the **Model Factory**:

1. prepare runtimes/models;
2. define panels/regions used for training data;
3. create and maintain canonical geometry Ground Truth;
4. build/train/evaluate the geometry/table detector;
5. iterate detector vs canonical GT until the geometry is sufficient;
6. materialize **Recognition Ground Truth** directly from canonical cells;
7. review `crop -> exact visible text` without functional field mapping;
8. build/validate the recognition dataset;
9. train/evaluate/activate the recognition model;
10. expose the detector + recognition artifacts as the model bundle.

Recognition is therefore part of the Model Factory, not Application Processing.
The recognition model learns literal text. Examples:

```text
pixels -> "HR"
pixels -> "79 bpm"
pixels -> "-"
```

A lone `-`, `–` or `—` remains literal recognition Ground Truth. It is **not**
converted to missing/null while training the recognition model.

A model bundle may contain multiple technical artifacts (for example a geometry
model and a recognition model), but the bundle itself remains application-neutral.
Recommended manifest contents are model versions, preprocessing requirements,
class/dictionary metadata, evaluation metrics and runtime compatibility.

## Recognition GT is independent from Mapping Studio

Recognition training must not depend on a relation such as `HR -> heart_rate`.
Neutral Recognition-GT samples are created directly from the canonical table-cell
Ground Truth and use stable technical sample identifiers. Their only semantic
label is the exact visible text entered by the reviewer.

The recognition-dataset builder only consumes accepted samples with the neutral
`canonical_gt_cell` extraction method. Historical `mapped_generic` samples from
Application Mapping are deliberately excluded from model training.

This makes the dependency direction explicit:

```text
canonical geometry GT
        -> recognition crops
        -> exact text GT
        -> recognition dataset
        -> recognition model
        -> MODEL BUNDLE
```

There is no Application Mapping dependency anywhere in that chain.

## Optional phase 2: Application Processing

Turning model/OCR output into domain/application output is a separate concern and
is not a model-training prerequisite. Existing Mapping Studio work is deliberately
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

At this point a raw value such as `-` may be interpreted as `missing/null` by the
application profile. That interpretation is intentionally later than recognition
training.

None of `HR`, `bpm` or `heart_rate` needs to be taught to the Model Factory as an
application rule. The model only needs to read the text; aliases/units/output names
belong to the selected application profile.

## Compatibility policy

The Mapping Studio, mapping database, fullscreen reviewer, relation feedback,
canonical-GT mapping build and schema-scoring code are retained. Existing mapping
data is not migrated or deleted by the Model Factory split.

Application-only semantic helpers live under:

`isala_ocr.application_processing`

The old `training.mapping_semantics` and `training.mapping_lateral` modules are
compatibility shims. Historical Mapping jobs/routes remain available as optional
Phase 2 functionality.

## Boundary rule

A feature belongs in **training/model factory** when it affects model artifacts or
the training/evaluation data used to produce those artifacts. Geometry GT,
Recognition GT, recognition datasets and recognition training all satisfy this
rule.

A feature belongs in **application processing** when it changes how already-read
OCR content is interpreted, named, validated or serialized for a downstream use
case.
