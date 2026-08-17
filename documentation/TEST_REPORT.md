# Test report – IsalaOCR 3.14.0

## Automated regression suite

- 473 tests passed.
- 24 tests skipped because optional runtime-only dependencies or platform services are unavailable in the packaging environment.
- No test failures.

## v3.14.0 regression coverage

- A Step-3 table-first detection now carries an immutable detection-batch identity plus the exact table-cell model/training-run/dataset used for that pass.
- Activating model v2 after a model-v1 detection cannot relabel the existing v1 predictions as v2; Step 7 reports the detection as stale and requires a new Step-3 pass.
- A fresh v2 detection becomes the only active writable Step-7 review; v1 stays available as read-only history and its review decisions are not inherited by v2.
- Historical model runs can be re-evaluated in memory against the current canonical GT when panel geometry is unchanged, without rewriting archived predictions.
- The newest fully completed Step-7 review becomes dataset/training feedback. Only explicit `model_error` decisions create hard examples.
- FP/FN/geometry model errors receive x3 train weighting and merged-cell model errors x4; `functional_ok` is not penalized.
- Hard-example copies are created only in TRAIN. VAL and TEST are unchanged, preserving honest comparison metrics.
- A newer completed run with zero model errors supersedes previous hard-example feedback so old failures do not remain permanently oversampled.
- Dataset currentness now includes both the canonical-GT fingerprint and the latest completed review-feedback fingerprint.
- Continuation training supports the active custom model's original `.pdparams` checkpoint, a lower continuation learning rate, parent-model metadata and safe fallback to the official pretrain.
- Step 6 now distinguishes whether the next required action is dataset rebuild, validation, training, activation or re-detection instead of always treating an active model as the endpoint.
- Existing canonical-GT readiness, containment recovery, functional-correct review, reverse highlighting, AJAX review and worker-refresh behavior remains covered.

## Static/package checks

- TypeScript embedded build compiled successfully (`tsconfig.json`, `tsconfig.quality.json`, `tsconfig.artifacts.json`).
- 32 Jinja templates compiled successfully.
- Shared JavaScript and the modified Step-7 inline JavaScript pass syntax checking after template-independent extraction.
- Package manifest hashes and ZIP integrity are verified after packaging.

## Environment limitation

The packaging environment does not provide the target Windows Docker Desktop/NVIDIA/Paddle runtime. Runtime image/build smoke tests that require those services must execute on the target host; the portable regression suite and static checks pass in the packaging environment.
