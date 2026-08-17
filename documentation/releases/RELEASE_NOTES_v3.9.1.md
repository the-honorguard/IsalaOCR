# IsalaOCR 3.9.1 — detector-quality diagnostics and reactive gate state

v3.9.1 extends the React migration from Step 4 into the detector-quality workflow and fixes the stale Detection Gate explanation that could survive after a new evaluation.

## Detection Gate state is now derived from current evidence

A trained evaluation now stores a fingerprint of the exact reviewed ground truth, immutable dataset split and evaluated source scope. The UI derives the current gate state from that fingerprint, the latest trained evaluation, the active field detector and the configured hard thresholds.

This distinguishes:

- **OPEN** — the active model has a passing evaluation on the current ground truth/scope;
- **FAILED** — the latest current trained evaluation does not meet the configured metrics;
- **AWAITING ACTIVATION** — the trained model passes but has not been activated;
- **STALE** — ground truth/dataset scope changed after evaluation;
- **NOT EVALUATED** — no trained evaluation is available.

Activation also checks the current fingerprint, so an old passing result cannot be activated after geometry or split changes.

## Low-threshold inference and confidence sweep

Trained-detector evaluation now generates predictions once at confidence `0.01`. The canonical gate remains evaluated at the configured operating threshold `0.25`, while a diagnostic sweep scores the same predictions at:

`0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.35, 0.50`

For every threshold the report records prediction count, TP, FP, FN, precision, recall, IoU, auto-accept rate and gate result.

The same sweep is performed independently on **train**, **validation** and **test** splits. This makes it possible to distinguish low-confidence calibration from underfitting/export/inference failures and from a train→test generalisation gap.

Step 5 can rerun these diagnostics for the latest existing trained model; retraining is not required just to obtain the sweep.

## React migration phase 2

Steps 5/6/7/9 now share a React detector-quality workbench with REST + Server-Sent Events. Evaluation, comparison, activation readiness, quality reporting and threshold diagnostics update without a full-page reload.

The Python backend, SQLite project state, PowerShell worker queue, Docker/PaddleX runtime and hard detection thresholds remain authoritative.
