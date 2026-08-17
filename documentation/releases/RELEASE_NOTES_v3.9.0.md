# IsalaOCR 3.9.0 — reactive web interface, phase 1

v3.9.0 starts the incremental migration from server-rendered workflow pages to a reactive browser client. The Python backend, project isolation, SQLite training state, PowerShell worker queue, Docker/PaddleX runtime and immutable dataset semantics remain authoritative and unchanged.

## Step 4 is now a React/TypeScript workbench

**Stap 4 · Dataset & detector trainen** is the first migrated screen. Dataset preview/splits, build, IsalaOCR/PaddleX validation, readiness and GPU/CPU detector training are rendered by a React/TypeScript client instead of the legacy Jinja page logic.

The browser does not perform full-page reloads to synchronize Step 4. State changes update only the relevant React components, preserving scroll position and local UI state.

## REST + Server-Sent Events

The new frontend boundary is deliberately framework-independent on the backend:

- `GET /api/v2/localization/workbench` returns canonical Step 4 state and the exact dataset preview used by the builder.
- `POST /api/v2/localization/split` updates automatic/count-based train/validation/test assignments and per-source overrides.
- `POST /api/v2/jobs` queues worker tasks without HTML navigation and rejects duplicate active submissions.
- `GET /api/v2/events` is an SSE invalidation stream. Small events tell the client which state must be refetched; complete workflow snapshots are not pushed on every heartbeat.

The existing `/api/localization-readiness` endpoint remains available for compatibility.

## Deployment model

The compiled frontend asset is checked into the application package, so the lightweight labeler image does not need Node.js or npm at runtime. React/ReactDOM are served locally with the application; the interface has no CDN dependency. TypeScript source and its build configuration live under `frontend/`.

This is intentionally an incremental migration. Detection Review and the other workflow pages remain on the existing server-rendered interface in 3.9.0 and continue to work alongside the new Step 4 client. The shared bottom activity dock also remains on its existing polling implementation for now.

## Training runtime

No heavy training image change is required. `project/TRAINING_IMAGE_VERSION` remains **3.8.4** and all v3.8.22 PaddleDetection training fixes remain included.
