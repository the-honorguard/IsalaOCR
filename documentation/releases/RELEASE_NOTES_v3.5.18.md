# IsalaOCR 3.5.18

## Structured study information

The Philips `Study info` line is now parsed during DICOM detection and added to the output as separate fields:

- `heart_rate_bpm`
- `bsa_m2`
- `bsa_method`
- `height_m`
- `weight_kg`
- `gender`

The full OCR line remains available as `raw_text`. Exact OCR fragments are also retained under `raw_values`, so the parsed value can always be compared with what the OCR engine actually returned.

## Output locations

Normal OCR output contains the new `study_info` object in both `result.json` and `result.txt`.

The training/detection workflow writes a directly consumable file per source:

```text
training/workspace/extracted_output/<source_id>.json
```

The detection page shows all six fields and provides an **Output-JSON openen** button.

## Privacy boundary

The new output contains only the requested on-screen physiological/demographic values. Patient name, patient number, accession number and DICOM UIDs remain excluded.
