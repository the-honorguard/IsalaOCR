# IsalaOCR Local v3.3.3

## Stale validation-output permission repair

The PP-OCRv6 dictionary was synchronized successfully, proving that the reviewed dataset itself is writable. The next failure occurred in the deterministic validation output directory, which had been created during an earlier run with a different container identity.

Version 3.3.3 prepares run directories on the Windows host before Docker starts. Menu option 8 removes and recreates only `training/workspace/runs/check-<dataset-id>` because that directory contains disposable validation output. Training, evaluation and comparison create their unique output directories on the host and verify them with a temporary write probe.

No DICOMs, crops, reviews, exact labels, SQLite database, dataset split or trained model are removed. `fixed_fallback` remains limited to bootstrap crop collection.
