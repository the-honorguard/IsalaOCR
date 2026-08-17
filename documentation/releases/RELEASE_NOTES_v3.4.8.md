# IsalaOCR v3.4.8

## Compact training progress and durable full logs

PaddleOCR normally emits multiple batch lines plus validation, `best_accuracy`, `latest`, epoch-checkpoint and inference-export messages during every epoch. Those messages describe separate checkpoint artifacts and do not mean that the same training action is accidentally launched multiple times.

This release adds a compact training console that:

- shows four clear phases: initialization, dataset loading, training and finalization;
- renders one total progress bar per completed epoch;
- shows epoch/total, validation accuracy, best accuracy and epoch, loss, ETA and allocated GPU memory;
- suppresses repetitive checkpoint/export noise from the console only;
- preserves the complete unfiltered output as `training-console.log` in the run directory;
- writes a machine-readable live status file as `training-progress.json` after each update;
- automatically passes through tracebacks, warnings and errors;
- supports `-DetailedOutput` on `train-recognition-model.ps1` when the full stream is also wanted on screen.

Training, validation and checkpoint semantics are unchanged. The existing training image revision remains `3.3.12`, so option 1 and an image rebuild are not required.
