# IsalaOCR Local v3.3.1

## PP-OCRv6 dictionary embedded in the training image

PaddleX 3.7.2 contains the `PP-OCRv6_medium_rec` configuration, but its source distribution does not contain the separate PaddleOCR repository file referenced as `ppocr/utils/dict/ppocrv6_dict.txt`. Version 3.3.0 therefore could not materialize `dataset/dict.txt`.

Version 3.3.1 fixes this at Docker build time:

- downloads the official `ppocrv6_dict.txt` from a pinned PaddleOCR commit;
- verifies the complete file against its Git blob SHA-1;
- stores it at `/opt/isala-training-resources/ppocrv6_dict.txt`;
- uses that deterministic local file for dataset validation, training and evaluation;
- retains a compatibility search for images that contain a complete PaddleOCR checkout;
- preserves exact labels and spaces and does not alter existing crops, reviews or datasets.

No runtime internet access is required after the training image has been built. `fixed_fallback` behavior is unchanged and remains limited to bootstrap crop collection.
