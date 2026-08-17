# IsalaOCR v3.8.1 — Labeler project-module hotfix

This hotfix repairs web-interface startup after the v3.8.0 project-workspace introduction.

## Fixed

- Add `isala_ocr.training.projects` to the dedicated lightweight labeler image. v3.8.0 imported this module from `webui.py`/`mapping.py`, but `Dockerfile.labeler` did not copy it, causing `ModuleNotFoundError` before the HTTP server could start.
- Add regression coverage that checks the labeler Dockerfile contains every direct local Python module imported by the web UI and its copied lightweight dependencies.
- Keep the labeler image lightweight; PaddleOCR, PaddlePaddle, OpenCV and pydicom are still excluded.
- Replace the non-ASCII middle dot in Windows prerequisite project-path output with `|` to avoid `Â·` mojibake under Windows PowerShell 5.1 consoles.

## Upgrade

Extract v3.8.1 over v3.8.0 and run `START.cmd`. Docker Compose will rebuild only the lightweight `isalaocr-labeler:3.8.1` image. The heavy training-image revision remains `3.7.0`.
