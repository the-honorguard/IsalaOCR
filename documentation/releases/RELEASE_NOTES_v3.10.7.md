# IsalaOCR 3.10.7

Step 5 now turns a failed detection gate into an inspectable diagnosis instead of only showing aggregate metrics.

## Visual detection diagnosis

- Test renders show **TP (green)**, **FP (red)** and **FN (orange)** boxes.
- False positives are categorized into duplicate/NMS, localization/IoU, explicit negative-region and unmatched cases.
- Clicking a box explains why it received that classification and shows confidence/IoU context.
- Unmatched red boxes can be explicitly confirmed as missing ground truth; this is never automatic and intentionally invalidates the current dataset/evaluation until Detection Review and dataset build are completed again.
- Each source lists TP/FP/FN counts so the worst images can be inspected first.

## Confidence calibration

The existing confidence sweep is now actionable from the UI and covers thresholds through 0.95. Selecting a threshold redraws the same saved predictions immediately; no detector inference or retraining is required. This makes it possible to see whether false positives disappear through threshold calibration or whether recall collapses at the same time.

The heavy training image stays at `TRAINING_IMAGE_VERSION=3.8.4`; this release only changes application/WebUI code.
