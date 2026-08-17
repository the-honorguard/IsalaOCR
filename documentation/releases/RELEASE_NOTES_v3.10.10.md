# IsalaOCR 3.10.10

Step 5 is now an explainable detector-diagnostics workbench.

- Every important metric is described directly in the UI.
- Confidence calibration uses VALIDATION; TEST is never used to select production confidence.
- If validation cannot satisfy the gate, the UI explicitly reports that no production threshold exists yet.
- The visual TP/FP/FN view can re-score the same saved predictions at different diagnostic IoU thresholds. The canonical Detection Gate IoU remains unchanged.
- FP causes are presented as near-match/IoU, duplicate, negative-region, and unmatched (which still requires visual review to distinguish a real FP from missing ground truth).

No model retraining or dataset rebuild is required to use the new visual explanations and IoU diagnostics. Re-run the confidence diagnostic/evaluation only if you want the new validation-calibration metadata persisted in `latest_trained.json`; the UI can derive calibration from existing split rows as well. Restart/rebuild the labeler web interface so image `isalaocr-labeler:3.10.10` is used.
