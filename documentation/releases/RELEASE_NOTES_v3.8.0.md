# IsalaOCR v3.8.0 — Project Workspaces

## Generic tooling, isolated project-specific models

- Adds a persistent **Project selector** to the web UI. Every project has its own workspace, reviews, localization datasets, detection gate, mappings, OCR reviews, recognition datasets and model state.
- Adds discoverable **use-case templates** under `application/config/use_cases`. The current testcase is `philips_cmr_volume_results`; `generic_document` is an empty template for other document types.
- Localization and recognition registries/active models are project-specific. Shared Paddle/PaddleX caches and Docker tooling remain platform-wide.
- Queued worker jobs are pinned to the project that created them through `ISALA_PROJECT_ID`; switching the UI project cannot redirect an already queued/running job into another workspace.
- New projects receive a project-specific input path (`/input/projects/<project-id>` by default). The migrated first project keeps `/input` for backwards compatibility. The configured input path is visible on the Projects page and used by detection/redetection/mapping preparation.
- Projects can be created, switched, renamed, archived and duplicated. Duplication is a consistent SQLite snapshot and keeps the same use-case to prevent accidental cross-use-case model/data contamination.

## Explicit review supervision

The v3.7.6 requirement to finalize every detected candidate before dataset building is removed. Localization training now uses only **explicit human decisions**:

- `Correct`, `Aangepast` and manually added boxes = positive examples.
- Explicit rejection or `Niet nodig voor dit project` = negative examples for that project's specialized detector.
- Unreviewed candidates = unknown and are excluded from supervision.
- Rejection/scope reasons are optional audit metadata; the object detector does not use the reason code as a training target.

Partially reviewed screenshots are converted into contextual positive/negative training patches. This prevents unreviewed desired fields elsewhere on the screenshot from being silently learned as background. Fully reviewed screenshots may be used as complete full-image supervision.

The existing fast review controls remain: Shift-click ranges, Ctrl/Cmd additive selection, selection rectangle, batch positive/negative actions, keyboard shortcuts and single-ROI resize/move for corrected ground truth.

## Migration

On first start, an existing single 3.7.x workspace is migrated to project `cmr_testcase_01`. Existing detection/review/mapping/training state is moved below `training/workspace/projects/cmr_testcase_01`. Existing recognition registry/active-model state is copied lazily into the first project's namespace. Raw `input` remains the first project's input source for backwards compatibility.

Database schema remains v12; project isolation is implemented by separate project databases/workspaces rather than adding `project_id` columns to the existing tables.
