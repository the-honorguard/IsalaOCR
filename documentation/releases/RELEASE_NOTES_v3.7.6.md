# IsalaOCR v3.7.6

## Localization review readiness and reliable job failures

- COCO localization dataset building now refuses partial/unfinalized detection review with an actionable count of pending candidates.
- Detection Review index can finalize all remaining open candidates across all sources in one explicit bulk action after exception review.
- A completed review with zero relevant positives reports the review totals instead of a generic error.
- The PowerShell worker records the child launcher exit code in a sidecar file and has a fatal-output safety check, preventing failed actions from being shown as successfully completed.
- Regression coverage added for dataset readiness, global finalization UX and worker exit-code propagation.
