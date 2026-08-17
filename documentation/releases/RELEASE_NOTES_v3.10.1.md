# IsalaOCR 3.10.1

This maintenance release focuses on WebUI correctness and runtime efficiency without changing the local-only security model.

## Fixed

- Jobs submitted through the classic WebUI route now retain the project ID and project name from the project in which they were queued. Switching projects before worker pickup no longer changes the job target.
- `/models` now redirects to the canonical Projecten & modellen screen; the obsolete template could submit action IDs whose meaning changed in newer releases.
- SQLite connections now roll back when an operation raises an exception.
- Preparation inventory refresh can run again after a snapshot becomes stale and can retry after a failed refresh attempt.

## Performance

- The active-project database is cached instead of reconstructing and reinitializing `TrainingDatabase` for every proxied database method call.
- Database schema initialization uses `PRAGMA user_version` as a fast path and only executes migration/setup SQL when required.
- Mapped recognition state is calculated with one aggregate SQL query instead of materializing up to 100,000 sample rows.
- The activity-dock `/api/status` poll no longer builds the complete pipeline snapshot.
- Recursive model/training file inventory is performed by the host preparation-status action and stored in `preparation_status.json`, rather than rescanning the bind-mounted model tree from the WebUI every two seconds.
- Activity polling is reduced from 1.5 seconds to 2.5 seconds.

## Verification

- Python test suite: 354 passed, 22 skipped in the build environment.
- Embedded TypeScript build: successful.
