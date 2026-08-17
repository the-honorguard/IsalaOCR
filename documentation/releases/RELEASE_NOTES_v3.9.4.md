# IsalaOCR 3.9.4 — lightweight Detection Gate hotfix

v3.9.4 fixes a WebUI runtime error introduced by the derived Detection Gate state in 3.9.3.

- Move `passes_detection_gate` into dependency-light `training/detection_gate.py`.
- Keep the public import through `training/localization.py` compatible for existing CLI/tests.
- Make `localization_dataset.derived_detection_gate_state()` use the lightweight gate module directly.
- Copy the new lightweight module into `Dockerfile.labeler`; do **not** pull the heavy OpenCV/OCR localization module into the WebUI image.
- Add regression tests that verify the WebUI gate dependency is copied and remains free of OpenCV/NumPy/OCR imports.
- Keep heavy `TRAINING_IMAGE_VERSION` at 3.8.4. Only the small labeler/WebUI image needs rebuilding.
