# IsalaOCR v3.4.6

## Exact training-image materialization

Option 1 no longer uses the generic timed image probe to decide whether a new versioned training image should be built. It always asks Docker Compose to materialize the exact CPU and GPU tags. Existing layers are reused through BuildKit.

After each build, the exact expected image is checked directly:

- `isalaocr-training-cpu:3.3.12`
- `isalaocr-training-gpu:3.3.12`

The CPU image is checked a second time immediately before the offline `training-setup` container is launched. A missing tag now produces a targeted host-side error instead of Docker's `No such image` response.

The training image revision remains `3.3.12`; only host automation and application metadata changed.
