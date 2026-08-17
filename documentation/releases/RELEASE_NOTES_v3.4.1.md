# IsalaOCR 3.4.1

## Pretrained-weight download boundary

- The official PP-OCRv6 medium pretrained weight is downloaded by the same network-enabled `model-prep` container that prepares inference models.
- `training-setup` is now explicitly offline and only validates the locally cached weight and training source.
- Before a missing weight is downloaded, the pipeline performs a host connectivity check and then an exact Docker-container connectivity probe.
- Cached weights larger than 1 MiB bypass all network checks and downloads.
- Incomplete `.part` files are removed automatically after download errors.
- The reusable CPU and GPU training image revision remains `3.3.11`; no CUDA or PaddlePaddle rebuild is required.
