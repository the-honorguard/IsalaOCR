# IsalaOCR 3.8.17 — compact progress-first activity dock

- Keep the bottom activity terminal collapsed when a job starts.
- Show only a compact 44 px progress/status bar by default while tasks run.
- Do not auto-expand the terminal for newly submitted jobs, selected jobs, or `job_id` URLs.
- Preserve explicit user expansion separately from the legacy auto-open preference so upgrades start compact.
- Keep failures visible in the compact status bar without forcing STDOUT/STDERR open.
- Heavy training image revision remains 3.8.4.
