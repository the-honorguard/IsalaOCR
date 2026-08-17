# IsalaOCR 3.8.13 — Fast Detection Review and dataset eligibility

## Exception-first Detection Review

Detection Review now uses four primary decisions in the bottom selection dock: **Includeren**, **Niet relevant**, **Incorrect** and **Kader aanpassen**. Incorrect detections can carry an optional detector-error reason. Geometry editing is handled from the same dock instead of a second, competing review control set.

Review writes are queued per ROI and processed in the background with limited concurrency. The UI advances immediately, persists queued work in the browser, retries transient failures and prevents source completion from overtaking unfinished or failed ROI writes.

`Rest standaard includeren` is enabled by default. When **Afbeelding klaar** is selected, remaining open ROI candidates are queued as positive includes; turning that option off requires every ROI to be reviewed explicitly.

## Image-level completion gate

`Afbeelding klaar` is a persistent source-level state. Any later ROI review, manual annotation or re-detection invalidates that state. Only completed source images are eligible for localization training; incomplete images contribute no positive, negative or background supervision.

The former separate **Detectiereview status** workflow step has been removed. Source completion and counts are visible directly in Detection Review. The workflow is renumbered contiguously.

## Dataset preview

The localization dataset step now previews the exact input selection before building. It reports total, included and excluded images; positive and negative ROI counts; adjusted, incorrect, irrelevant and manually added ROI counts; train/validation/test source splits; and a per-source inclusion table with a direct link back to review. The preview and builder share the same completion rule and split function.

This is an application/workflow release. `TRAINING_IMAGE_VERSION` remains **3.8.4**.
