# PaddleDetection compatibility hooks

This directory is prepended to `PYTHONPATH` only for PaddleDetection processes. It intentionally does not change PaddleOCR recognition training.

- `pkg_resources.py` supplies the legacy compatibility surface required by the pinned PaddleDetection stack.
- `sitecustomize.py` installs IsalaOCR's table-cell hard-example replay hook only during detector training. It extends PaddleDetection's in-memory train `roidbs` with weighted references to difficult full panels, so every replay draw still goes through the normal shuffled sampler and training augmentations. The canonical COCO files and PNG files stay single-copy.

The replay hook writes `evaluation_artifacts/hard_example_replay_runtime.json`. `table_cell_runner.py` treats a missing or mismatched marker as a failed training run whenever replay was planned; this prevents a silently ignored sampler policy from producing an apparently valid model.
