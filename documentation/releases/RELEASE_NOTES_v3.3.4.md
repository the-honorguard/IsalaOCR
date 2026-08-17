# IsalaOCR Local v3.3.4

## Offline PaddleX dataset-preview font

PaddleX dataset validation generates preview material and lazily requests
`PingFang-SC-Regular.ttf` when no local font is configured. The training
containers intentionally use `network_mode: none`, so that unrelated runtime
download failed before PaddleX could finish option 8.

This release:

- copies Matplotlib's bundled `DejaVuSans.ttf` into the training image during the Docker build;
- validates that the copied font can render IsalaOCR numeric and unit characters, including `²`;
- sets `PADDLE_PDX_LOCAL_FONT_FILE_PATH` in the image and all three PaddleX services;
- keeps dataset validation, training, evaluation and export offline at runtime;
- does not include or distribute a separate font file in the source ZIP.

The reviewed dataset, labels, SQLite database, splits and model files are not modified.
`fixed_fallback` remains limited to bootstrap training-data collection.
