# IsalaOCR Local v3.3.2

## Training workspace UID/GID alignment

The dataset was created by the regular IsalaOCR runtime as UID/GID `10001:10001`, while the PaddleX base image used a different runtime identity. The training container could read the existing dataset but could not add the required `dict.txt` and `dictionary_manifest.json` files.

Version 3.3.2 runs every PaddleX service with the same numeric identity as the collector and dataset builder. This repairs the permission contract without running the trainer as root and without changing permissions recursively on the user's reviewed training data.

Existing datasets do not need to be rebuilt. Menu option 8 can synchronize the pinned PP-OCRv6 dictionary into the current dataset and continue with PaddleX validation. The 224 reviews, exact spaces, crops, SQLite database and split assignment remain unchanged.

`fixed_fallback` remains limited to bootstrap crop collection; this release does not introduce production fixed coordinates.
