# IsalaOCR Local v3.3.5

## Offline baseline model preparation

Menu option 9 evaluates `PP-OCRv6_medium_rec` while the evaluator container has no network access. Earlier releases prepared the normal small detection/recognition pipeline and the medium training weights, but did not prepare the medium **inference** model used by the baseline evaluator. PaddleX therefore attempted a runtime download and failed because `network_mode: none` is intentional.

Version 3.3.5:

- prepares the training configuration's default recognition model during menu option 1;
- stores the official medium inference model in the shared PaddleX cache;
- resolves that local official cache explicitly during recognition-only evaluation;
- ensures a named baseline cannot be replaced by an activated custom model;
- refuses runtime downloads in offline mode and reports the expected local path;
- performs a Windows-side cache preflight before starting option 9;
- verifies during preparation that the medium inference metadata and weights are present.

Existing reviews, crops, datasets and training runs are not modified. Install this version and rerun menu option 1 once, followed by option 9.
