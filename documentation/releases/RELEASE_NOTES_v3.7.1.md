# IsalaOCR 3.7.1 — Web startup / action-catalog hotfix

## Fixed

- Restores `START.cmd` web startup after the v3.7.0 pipeline renumbering. The web entry point uses action 3 and is now explicitly registered in the shared PowerShell action catalog.
- Adds a dedicated `webui-start` preflight profile so startup validates the local web server and PowerShell worker before Docker builds/starts the labeler.
- Includes action 3 in container bind-mount permission verification when the reusable training image is available.
- Corrects legacy recognition compatibility scripts so they no longer reuse action numbers that v3.7.0 reassigned to localization operations.
- Makes old labeler utility scripts use the web-interface preflight instead of accidentally invoking localization dataset checks.
- Adds regression tests that verify all literal PowerShell preflight IDs exist in the catalog and that the web startup entry is registered.

## Upgrade

Extract 3.7.1 over the existing 3.7.0 project. Existing `input`, `output`, `models` and `training` data remain compatible.

The reusable training image revision intentionally remains **3.7.0** because this hotfix changes host-side PowerShell/catalog logic only. Existing CPU/GPU training images therefore do not need to be rebuilt solely for this update.
