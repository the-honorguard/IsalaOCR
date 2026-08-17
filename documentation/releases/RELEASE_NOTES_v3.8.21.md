# IsalaOCR 3.8.21 — PaddleDetection pkg_resources compatibility + live Step 4

## Field detector training

PicoDet-S training could still fail after a fully green dataset/preflight when an older reusable GPU-detection image did not expose the deprecated `pkg_resources` module required by PaddleDetection `ppdet.model_zoo`.

v3.8.21 adds a bounded compatibility module under `automation/training_runtime/paddledet_compat`. The localization runner prepends this directory only to nested PaddleX/PaddleDetection subprocesses. Because `automation/training_runtime` is already bind-mounted into the trainer container, the fix works with the existing `isalaocr-training-gpu-detection:3.8.4` image and does not require a multi-gigabyte rebuild.

The runtime check now imports `ppdet.model_zoo.model_zoo` explicitly so the exact legacy dependency path is tested before training.

## Step 4 live readiness

Step 4 now listens for local job state transitions from the shared activity dock. After localization validation finishes, the page fetches `/api/localization-readiness` and updates IsalaOCR/PaddleX/split/ready-marker indicators plus the GPU/CPU training buttons in place. No manual browser refresh is required. Dataset builds and completed training runs still trigger one automatic page refresh because they replace larger dataset/model tables.

## Compatibility

- Existing detection review and localization datasets remain valid.
- Existing successful validation markers remain valid.
- Heavy training image revision stays `3.8.4`.
- No GPU/CPU training image rebuild is required for this hotfix.
