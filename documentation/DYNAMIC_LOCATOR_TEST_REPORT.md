# Dynamic locator test report — v3.2.0

## Automated tests

- 53 regression tests passed.
- Covered label-row matching, changed row order, ED/ES and BSA discrimination, database migration fields, changed-crop review invalidation, placeholder classification and queue exclusion.

## Real-screen smoke test

The 14 supplied DICOM screenshots were converted locally to PNG only for this engineering test. The dynamic locator was then exercised with Tesseract 5.5 as an independent detector fallback; recognition output itself was stubbed so this test measured localization rather than OCR accuracy.

Results:

- input screens: 14;
- expected fields: 224;
- dynamic row crops: 215;
- marked fixed fallbacks: 9;
- failed input screens: 0;
- locator overlays generated: 14.

The reordered 1919×1012 layout was correctly mapped by screen label: `rv_stroke_volume` was cropped from the `Stroke Volume` row (`80.7 ml`) rather than the later `ED Volume/BSA` row (`82.8 ml/m²`).

## Limitation

The production collector uses PaddleOCR PP-OCRv6 detection, not Tesseract. Paddle inference could not be executed in this build environment. The first Docker collect run on the target workstation remains the definitive integration test. Inspect `training/workspace/locator_overlays` and review all `fixed_fallback` samples before building a training dataset.
