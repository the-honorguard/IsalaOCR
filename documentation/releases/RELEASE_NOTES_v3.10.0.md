# IsalaOCR 3.10.0

This release fixes stale/incorrect preparation status reporting. The browser no longer treats an old host inventory snapshot as current truth. Step 1 refreshes preparation state through the existing worker queue and updates the matrix in-place.

`Alles controleren` now completes the inventory for all five preparation components even when one component is missing. A missing `isalaocr-training-gpu:3.8.4` is specifically the OCR-recognition training image; field-detector training uses `isalaocr-training-gpu-detection:3.8.4`.
