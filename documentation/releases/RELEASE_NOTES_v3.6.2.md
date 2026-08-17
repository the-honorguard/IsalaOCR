# IsalaOCR 3.6.2

## Paddle table structure and mapping preview

This release adds a table-aware structural layer before semantic mapping while keeping the generic OCR fallback for non-table data.

- Added a lazy PaddleOCR **PP-StructureV3** table pipeline to the model preparation and detection flow.
- **Alle modellen downloaden** now also materializes the table/layout/cell models required by PP-StructureV3 when table structure is enabled.
- Table detection remains fail-open: a source can still use generic OCR relationships when PP-StructureV3 cannot identify a usable table.
- PP-Structure cell boxes are stored separately from raw OCR tokens, with stable table, row and column metadata.
- Detected table rows produce explicit `table_cell` label/value relations. The first value cell to the right of a label is the primary automatic mapping candidate; later cells remain available as secondary/reference values.
- Table relations take precedence over overlapping nearest-neighbour OCR relations, reducing duplicate and ambiguous mapping proposals.
- Final ROI geometry is not blindly taken from the complete table cell. The mapper first selects the exact full-page OCR tokens inside the chosen value cell and unions their original boxes. The table cell itself is only the geometry fallback.
- Detectieweergave now includes a **Paddle tabelstructuur** mode and exposes table, row and column metadata.
- Mappingstudio explicitly marks **Paddle tabel** versus **OCR-relatie** proposals and shows the actual prospective value ROI crop.
- Added **Output-preview geselecteerde data** to Mappingstudio. Selecting a detected relation and functional field immediately shows the JSON object that mapping would produce, including parsed value/unit, range check, mapping confidence and table-source metadata.
- Database schema is upgraded to **v9** with table/cell metadata on generic blocks and relations. Existing samples, reviews, mappings, datasets, runs and models are retained.
- Generic detector version is now `generic-layout-v3-table-aware` and mapping engine version is `generic-mapping-v3-table-aware`.

## Upgrade action

After updating:

1. Run **Modellen → Alle modellen downloaden** once so the PP-StructureV3 table models are available locally.
2. Run **Velden detecteren** again for existing sources. Old generic detections do not contain table/cell metadata.
3. Review the new table-based proposals in **Mappingstudio** and confirm the intended functional fields.
4. Re-run **Mapping toepassen** to materialize ROI crops from the new confirmed relations.

The normal OCR and mapping fallback remains available for loose key/value information such as HR, BSA, height, weight and gender when it is not part of a detected table.
