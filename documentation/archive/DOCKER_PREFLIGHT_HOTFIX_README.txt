IsalaOCR Docker preflight hotfix v3.2.1
======================================

Install
-------
Extract this ZIP directly into the existing IsalaOCR_docker project root and
replace existing files. Do not create an extra nested IsalaOCR_docker folder.

Then run:
  Get-ChildItem -Recurse -File | Unblock-File
  .\TRAINING_MENU.cmd

Fixes
-----
- Accepts a complete successful Docker Desktop response under Windows
  PowerShell 5.1 even when Start-Process does not expose ExitCode correctly.
- Refreshes the Process object before reading ExitCode.
- Starts Docker Desktop automatically when the Docker CLI exists but the
  Linux engine is not running.
- Waits up to 180 seconds and then automatically continues the selected action.

This patch does not contain or modify DICOM files, OCR models, crops, labels,
training databases, datasets, outputs, or registered models.
