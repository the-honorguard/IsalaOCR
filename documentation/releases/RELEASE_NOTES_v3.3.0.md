# IsalaOCR Local 3.3.0

## PaddleX dataset dictionary contract

PaddleX text-recognition validation requires `dict.txt` beside `train.txt` and `val.txt`. PaddleX training also replaces the model label dictionary with this dataset file.

IsalaOCR therefore does not generate a reduced dictionary from only the 224 local labels. Instead, validation, training and PaddleX evaluation synchronize `dict.txt` from the official PP-OCRv6 model dictionary inside the pinned training image. This preserves the pretrained output vocabulary and keeps spaces enabled through `use_space_char`.

Existing 3.2.x datasets are repaired automatically when option 8, 10, 11 or the PaddleX evaluation path runs. Rebuilding crops, reviews or the grouped dataset is not required. Exact labels remain byte-for-byte unchanged.

This release does not change the bootstrap `fixed_fallback` locator behaviour. Production `strict_dynamic` remains a separate architecture change.
