# IsalaOCR Local 3.2.8

The previous training image was based on PaddleX 3.3.11 and therefore did not contain the PP-OCRv6 medium recognition training configuration. Version 3.2.8 overlays the checksum-pinned official PaddleX 3.7.2 source distribution and explicitly installs PaddlePaddle 3.3.0 for CPU or CUDA 11.8 GPU builds.

Menu option 1 now fails during image construction when the expected `PP-OCRv6_medium_rec` configuration or PaddleX entry point is absent. Menu option 8 therefore no longer reaches a training image that can only report that the configuration is missing.

The release also retains the Path-aware discovery fix for `pathlib.Path` candidates.

This package contains no DICOMs, crops, reviews, database, generated datasets or model weights.
