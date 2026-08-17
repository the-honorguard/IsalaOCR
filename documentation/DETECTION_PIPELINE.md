# Field Detection & Crop Geometry — v3.8

## Purpose

Pipeline A answers only one question: **where are the useful field crops for the active project?** It deliberately does not decide what a field means and does not persist recognized values. Localization models may be highly specialized per project/use-case even though the surrounding tooling is generic.

## Candidate detection

For each rendered source image, IsalaOCR can combine:

- OCR/text detector geometry, with recognition text discarded;
- PP-StructureV3 table-region and table-cell geometry;
- the active trained field-detector predictions.

Candidate fusion deduplicates overlapping boxes and records provenance/confidence. Table regions and table cells remain separately inspectable overlays; they do not become label/value semantics in Pipeline A.

## Detection Review

Review is project-specific and exception-first. Detection itself never makes a source image eligible for training. The reviewer uses four primary actions from the bottom selection dock:

- **Includeren**: desired crop with usable geometry; stored as positive ground truth.
- **Niet relevant**: region that is not a target for this project; stored as negative/background supervision once the image is completed.
- **Incorrect**: detector error; stored as negative/background supervision and may carry an optional reason such as too small, too large, misplaced, false positive, merged fields, split field or table/cell geometry error.
- **Kader aanpassen**: edit the crop geometry and persist the corrected box as positive ground truth.
- **Handmatig toegevoegd**: draw a desired field that the detector missed; positive ground truth.

Review decisions are queued per ROI and written in the background with limited concurrency. The browser queue persists while navigating between source images. A failed explicit ROI write prevents the source-completion task from overtaking it.

`Rest standaard includeren` is enabled by default. Pressing **Afbeelding klaar** queues Include for any remaining open ROI candidates and then queues source completion. If default include is disabled, all ROI candidates must be decided explicitly before completion is allowed. Any later ROI/manual-annotation change or re-detection invalidates the completed state.

Reason codes are audit/analysis metadata; the object detector does not learn the reason label itself. Editing ground truth invalidates the active project's Detection Gate until a newly evaluated detector is activated.

## Localization dataset

Source completion is a hard dataset gate. Only images marked **✓ Afbeelding klaar** are eligible. An incomplete source contributes **nothing** to localization training, even if some individual ROI decisions are already stored. This avoids ambiguous background supervision and makes the training boundary easy to audit.

For each eligible source, the complete source image is exported to COCO. Positive/adjusted/manual boxes become `field_roi` annotations; regions marked Not relevant or Incorrect remain background/negative context. A completed source with no positive targets can therefore be a negative training image.

Before building, the dataset page computes an exact preview from the same review database and deterministic source split function used by the builder. It shows included/excluded image counts, positive/negative/adjusted/incorrect/irrelevant/manual ROI counts, train/validation/test source counts, and a per-source inclusion table.

The localization class remains `field_roi`; semantic field identity belongs to Mapping Studio/Pipeline B.

## Training

The v3.7 runtime integrates a PaddleX/PaddleDetection object detector, preferring PicoDet-S. Training actions are separate from PP-OCR recognition training because localization learns image -> bounding boxes, whereas recognition learns crop -> text.

## Evaluation and quality gate

Geometry is evaluated at IoU 0.75 with:

- recall;
- precision;
- mean and median IoU;
- false positives per image;
- auto-accept rate, i.e. predictions that match ground truth at IoU >= 0.90 without manual adjustment;
- independent test-image and ground-truth-ROI counts;
- full-screen false positives on sufficiently complete held-out review sources.

Default gate thresholds are configured in `application/config/app.yaml`. Evaluation does not open the gate automatically; activation of a passing trained detector is an explicit action.

## Pipeline boundary

Pipeline B may use OCR and table content to assign meaning, but `resolve_value_roi_box()` only accepts geometry supplied by Pipeline A. Reviewed annotations are authoritative over fresh machine candidates. This prevents semantic mapping logic from silently constructing a new crop after geometry review has completed.

## Bulk review controls (v3.7.5)

Detection Review supports batch selection for large review sets:

- click selects one candidate;
- Shift-click in the candidate queue selects a contiguous range;
- Ctrl/Cmd-click toggles individual candidates;
- **Selectievenster** (`S`) lets the reviewer drag a rectangle across the source image; candidates whose centre lies inside the rectangle are selected;
- Shift/Ctrl while drawing a selection window adds the matched candidates to the existing selection;
- Correct, detection-error and relevance actions apply to the full selection in one API request;
- geometry editing remains single-candidate only, because each adjusted ROI needs its own ground-truth box.
