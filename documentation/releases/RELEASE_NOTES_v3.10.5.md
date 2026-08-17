# IsalaOCR 3.10.5

## Fixes

- Hardened the Step 4 Dataset & detector training React screen against legacy or incomplete validation status payloads.
- The localization readiness API now always returns arrays for warnings/errors and an object for validation totals.
- Step 4 tolerates missing preview totals/source arrays and shows a recoverable warning when split metadata is absent.
- React render failures now expose the actual JavaScript error and provide a reload action instead of incorrectly suggesting that restarting the web interface will necessarily fix the problem.

No dataset IDs, model IDs, paths, or training semantics were changed.
