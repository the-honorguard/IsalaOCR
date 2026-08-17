# IsalaOCR 3.5.19

## Crop-first detection inspection

The **Detectieweergave** now shows the saved ROI crop in every card beside the source image. Selecting a crop or card highlights the corresponding overlay, so overlapping rectangles no longer have to be interpreted without context. Dynamic and fallback locations have separate badges; fallback rectangles use a dashed warning style.

## Actionable fallback repair

Every fallback card now states why the fixed profile coordinates were used, including the best observed row-header text, its locator score, the configured acceptance threshold and the expected canonical header.

When a header crop and raw OCR text are available, **Rijheader corrigeren** opens the exact sample in **Stap 3 · Rijheaders trainen**. The intended sequence is:

1. map the observed row header to the correct field;
2. save or accept the mapping;
3. choose **Trainen en DICOMs opnieuw detecteren**;
4. verify that the extraction method changes from `fixed_fallback` to a dynamic method.

If no header text was detected, the card explicitly reports that normalization cannot learn from that sample. The ROI can still be marked incorrect, but the real repair must then be made in header detection/preprocessing or in the fixed profile ROI.

## Compatibility

Existing crops, reviews, datasets and trained models remain compatible. Re-detection is only required after training a new header alias or changing detector/profile settings.
