# IsalaOCR 3.10.9

## Fix

Step 5 visual TP/FP/FN diagnostics no longer fail with `ModuleNotFoundError: isala_ocr.training.localization` in the lightweight labeler container. Geometry-only IoU and greedy matching now live in the dependency-light detection gate module that is already included in that image.

No model retraining or dataset rebuild is required. Restart/rebuild the labeler web interface so image `isalaocr-labeler:3.10.9` is used.
