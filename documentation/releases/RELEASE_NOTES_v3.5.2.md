# IsalaOCR 3.5.2

This release fixes the local PowerShell web worker on Windows PowerShell 5.1. Pending job JSON objects do not necessarily contain runtime fields such as `started_at`, `log_file`, `exit_code`, or `finished_at`. PowerShell `PSCustomObject` objects reject direct assignment to missing properties. The worker now uses a single `Set-JobProperty` helper backed by `Add-Member -Force`, allowing both new and existing queued jobs to be updated safely.

No DICOMs, reviews, datasets, models, runs, or queued jobs are removed.
