# IsalaOCR 3.5.8

Released 2026-08-06.

## Fixed

- The local web worker now executes action scripts through a temporary `cmd.exe` wrapper.
- The wrapper propagates the actual PowerShell action exit code with `exit /b %errorlevel%`.
- Successful actions are no longer marked as failed because Windows PowerShell 5.1 returned a null or stale child-process `ExitCode`.
- Temporary wrapper files are removed after every task, including failed tasks.

## Compatibility

No DICOM files, crops, reviews, datasets, training runs, registered models, or active models are changed by this update.
