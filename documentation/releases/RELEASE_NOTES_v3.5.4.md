# IsalaOCR 3.5.4

Fixes false **Worker not reachable** states caused by stale `worker.json` files or reused Windows process IDs. Worker identity now requires a recent heartbeat, the expected version, a PowerShell process and a command line containing `webui-worker.ps1`. Startup is verified for twelve seconds and diagnostic logs are written under `training/workspace/webui/jobs`.
