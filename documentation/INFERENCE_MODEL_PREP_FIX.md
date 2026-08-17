# Inference-model preparation fix v3.2.6

Menu option 1 now performs both required preparation stages:

1. The normal IsalaOCR runtime image downloads and smoke-tests the PP-OCRv6 small detection and recognition models used by crop collection.
2. The official PaddleX training image downloads the PP-OCRv6 medium recognition pretrained weight used for fine-tuning.

The training-only image no longer attempts to import `paddleocr`, because that package is not guaranteed to be present in the official PaddleX training image.

Both stages are verified on the host before option 1 reports success.
