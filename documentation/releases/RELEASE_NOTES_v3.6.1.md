# IsalaOCR 3.6.1

## ROI geometry correction

This maintenance release tightens the generic detection-and-mapping workflow introduced in 3.6.0.

- Adjacent visual rows are no longer merged through the growing union of earlier OCR boxes.
- Semantic labels are assembled only from consecutive nearby fragments; unrelated labels at the same y-coordinate stay separate.
- Each semantic value keeps a reference to the exact OCR token that supplied its geometry.
- Mapped ROI crops are resolved in a separate geometry step instead of blindly using an approximate semantic sub-box.
- Synthetic sub-boxes from combined OCR strings receive character-size sanity checks and adaptive padding before they become an ROI.
- Pathologically tall or wide value boxes are capped to plausible single-line text geometry.
- Automatic field mapping only uses the first/nearest value in a row. Later numeric values remain visible for manual mapping but are treated as likely reference-range values.
- Detectieweergave now defaults to mapping candidates (labels + values) instead of every semantic header block.
- Value crops in Detectieweergave and Mappingstudio show the prospective resolved ROI rather than the raw semantic sub-box.

After upgrading, run **Velden detecteren** once again. The detector version changed from `generic-layout-v1` to `generic-layout-v2`, so old generic block geometry should not be reused.
