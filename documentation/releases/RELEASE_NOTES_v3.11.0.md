# IsalaOCR 3.11.0

## Table-first localization experiment

The loose PicoDet/field-box detector is removed from the primary workflow for now. Existing detector datasets, runs, models and evaluations are preserved as a parked fallback.

The new primary localization flow is:

1. prepare the inference OCR + PP-Structure table stack;
2. run PP-StructureV3 on the source image without mixing OCR text boxes or the active field detector into the candidate set;
3. review the raw table-cell geometry, correcting inaccurate cells and drawing only cells Paddle missed;
4. calculate a TABLE-FIRST CHECK from that explicit review;
5. continue to Mapping Studio when table geometry is sufficiently complete.

The TABLE-FIRST CHECK reports:

- direct table coverage: desired cells PP-Structure supplied itself;
- exact-box rate: supplied cells that required no geometry correction;
- adjustment rate: supplied cells that required a corrected box;
- false-candidate rate: PP-Structure cells rejected as unusable;
- fallback need: desired cells that had to be drawn manually because Paddle did not supply them.

This release deliberately does **not** fine-tune a table model yet. It first measures the standard PP-StructureV3/table-cell pipeline on the current CMR images. If the standard model misses too much, the reviewed corrections are the basis for the next step: a dedicated wireless table-cell training flow. PicoDet remains available only under **Geparkeerd · box detector** so it can later be reintroduced for residual non-table regions if that is actually necessary.

Mapping/value jobs use the TABLE-FIRST CHECK as their primary geometry prerequisite. The legacy Detection Gate remains intact for the parked detector workflow.
