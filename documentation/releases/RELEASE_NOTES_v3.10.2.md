# IsalaOCR 3.10.2

This maintenance release focuses on WebUI response time and idle-load reduction. The local-only security model is unchanged.

## Interface performance

- Project catalog and active-project metadata are cached using file signatures, avoiding repeated JSON reads during database-backed page rendering.
- Registry state and derived Detection Gate state are reused across requests until their backing files/database change.
- Global activity polling and the localization React screens now poll adaptively: fast while work is active, slower while idle, and at a low rate in background tabs.
- Job status loading caches parsed job JSON, prefers the canonical status directory, filters by action/job type before expensive metadata work, and only inspects logs for jobs that are actually returned.
- Detection review overview counts are fetched with grouped SQL instead of per-source query loops.
- Mapping Studio preloads Pipeline-A annotations and candidates once per source, eliminating repeated geometry queries for each mapping relation.
- Source render decoding is reused across crop requests, while offscreen crop images use browser lazy loading and asynchronous decoding.
- Artifact directory-size scans use a short TTL cache.
- Localization readiness and quality APIs no longer construct the full home-page pipeline snapshot.
- Baseline and custom recognition evaluation discovery share one runs-tree scan.

## Behaviour

- No workflow semantics or local-only security behaviour were intentionally changed.
- During an active job, progress remains responsive; the reduced polling frequency applies primarily while the interface is idle or hidden.

## Verification

- Python test suite: 360 passed, 22 conditionally skipped in the build environment.
- Embedded TypeScript build: successful.
- TypeScript no-emit typecheck: successful.
- Python compile check and JavaScript syntax checks: successful.
