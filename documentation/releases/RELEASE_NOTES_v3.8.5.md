# IsalaOCR 3.8.5

## Preparation page / dependency status

- Centralizes all model downloads and reusable training-image preparation on **Step 1 · Modellen en trainingsimages voorbereiden**.
- Adds a requirements matrix for the five preparation components:
  - inference OCR + table models;
  - CPU detector / PicoDet-S stack;
  - GPU OCR-recognition image;
  - GPU PaddleDetection / PicoDet-S image;
  - PP-OCRv6 medium pretrained recognition weight.
- Shows a clear status per component: **Aanwezig**, **Ontbreekt**, or **Onbekend**.
- Adds an individual **Download / build** action only where a component is not ready.
- Keeps a single **Alles voorbereiden** action for first-time setup.
- Adds action **19 · Voorbereidingsstatus opnieuw controleren**. This performs host-side `docker image inspect` checks without downloading or rebuilding anything.
- Writes `models/preparation_status.json` as the host-side status snapshot so the lightweight web container does not need access to the Docker socket.
- Refreshes the snapshot after each successfully prepared component. This preserves accurate partial progress if a later component fails.
- Refreshes the snapshot once when the PowerShell web worker starts.

## Versioning

- Application/UI release: **3.8.5**.
- Heavy training-image revision intentionally remains **3.8.4** so the already-cached CPU/GPU images do not need to be rebuilt solely for this UI/status change.
