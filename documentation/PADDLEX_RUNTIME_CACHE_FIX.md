# PaddleX runtime-cache fix v3.2.5

PaddleX stores temporary files, file locks and cached function results below
`PADDLE_PDX_CACHE_HOME`. The model directory therefore cannot be mounted
read-only during inference or crop collection, even when model downloads are
disabled.

This update keeps network access disabled but makes the local `models` bind
mount writable for services that import PaddleX. It also validates cache
writability before importing PaddleX and initializes OCR engines once before a
batch. Existing model weights are reused and are not downloaded again.
