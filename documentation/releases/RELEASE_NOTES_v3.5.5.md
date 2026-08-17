# IsalaOCR 3.5.6

Fixes worker health and queue status synchronization on Windows PowerShell 5.1.

PowerShell 5.1 writes a UTF-8 BOM when `Set-Content -Encoding UTF8` is used. The Flask web container read these JSON files as plain UTF-8 and rejected them, so the worker appeared unavailable even while it was processing a task and producing logs.

Changes:
- worker heartbeat and task status JSON are written as UTF-8 without BOM;
- the web UI accepts existing BOM-prefixed JSON files;
- queued/running/completed/failed state refreshes correctly;
- no training images need rebuilding.
