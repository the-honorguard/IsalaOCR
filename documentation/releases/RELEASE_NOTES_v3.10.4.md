# IsalaOCR 3.10.4

## Artifact names and prerequisite guidance

- Datasets now use a human-readable UI label based on project name plus local date and time, while the immutable technical `loc-*` ID remains visible underneath for diagnostics.
- Field-detector models now show project, model family, device, date and time as the primary label; the stable technical model ID remains unchanged.
- Evaluation selectors and training runs use the same date/time-oriented presentation so related artifacts are easier to distinguish.
- Existing datasets and models receive the improved labels automatically from their stored timestamps; no rebuild or retraining is required.
- Disabled localization workflow actions now explain why they are unavailable and state the next required step.
- Dataset training readiness exposes explicit blockers for missing datasets, stale review/split state, IsalaOCR validation and PaddleX/PaddleDetection validation.
- Evaluation, comparison, activation and report actions expose missing prerequisites directly in the UI.
- Model activation in Data & modellen now explains gate, work-dataset and worker prerequisites before a user starts an action that cannot succeed.
