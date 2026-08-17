# IsalaOCR 3.5.0

This release replaces the fragmented menu-first workflow with one local web control panel.

## Web workflow

- Full DICOM render with selectable ROI overlays.
- Detected values, confidence, extraction method and review status beside the image.
- DICOM-level review of all fields in one form.
- Smart review for high-confidence dynamic detections with deterministic QA sampling.
- Exact pixel-duplicate propagation.
- Dataset, preparation, training, evaluation, registration and activation actions from the browser.
- Host-side job worker; the web container never receives the Docker socket.
- Live training progress and visual baseline/custom metrics.

`START.cmd` opens the web UI. Use `START.cmd menu` for the legacy console menu.
