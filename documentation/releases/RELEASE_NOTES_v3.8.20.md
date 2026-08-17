# IsalaOCR 3.8.20 — offline PicoDet training + live Step 4 refresh

## Fixes

- PicoDet-S detector training now uses a local pretrained weight from `models/training/PicoDet-S_pretrained.pdparams` instead of the network URL embedded in the upstream PaddleX config.
- The detector pretrain weight is downloaded by the network-enabled model-prep service and shared by CPU/GPU detector training. Training also performs a safe on-demand download when the weight is missing.
- PaddleX training stdout and stderr are merged into the live job stream and retained as `paddlex_train.log`, so the underlying training exception is no longer hidden by the PowerShell wrapper.
- Stap 4 automatically refreshes after build, validation or training reaches a terminal job state, so newly available buttons/statuses appear without a manual browser refresh.

The heavy training image revision remains 3.8.4.
