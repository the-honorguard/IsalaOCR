# IsalaOCR 3.6.0

## Generic detection before interpretation

The collector no longer starts by looking for a fixed list of Philips CMR fields. It performs full-page OCR and stores neutral text blocks, semantic label/value/unit candidates and possible spatial relationships. Every block has its own crop and source-image coordinates. Functional meaning is deliberately absent from this detection layer.

The configured Philips CMR profile remains available as starter data for the editable field schema and as compatibility information for existing workspaces. It does not restrict what the generic detector can discover.

## New mapping workflow

The web interface now follows twenty process-specific steps. The new front half is:

1. **Modellen** — prepare all models required by the configured pipeline;
2. **Bronnen** — inspect the neutral source set;
3. **Velden detecteren** — run generic full-page detection;
4. **Detectieweergave** — inspect overlays, crops and proposed relationships;
5. **Mappingstudio** — assign detected relationships to functional fields;
6. **Veldschema** — add and maintain fields, datatypes, units, aliases and ranges;
7. **Mappingprofielen** — save and apply reusable semantic rules;
8. **Mapping toepassen** — create ROI crops from confirmed mappings;
9. **ROI beoordelen** — assess crop geometry only;
10. **Waarden uitlezen** — recognize only approved ROI crops;
11. **Waarden beoordelen** — approve or correct exact OCR content.

The existing dataset, validation, training, export, evaluation, comparison, registration and activation steps continue after this flow.

## Mappingstudio and field schema

Automatic mappings use label aliases, section context, units and relationship confidence. They are always stored as suggestions until explicitly confirmed. Users can also select a field per relationship or manually combine a detected label block and value block.

The functional field schema is stored in the training database instead of being hardcoded in the detector. A field can define a group, datatype, preferred unit, aliases, validation range and required/optional state. New workflows can therefore be configured without changing Python source code.

## Mapping profiles

Confirmed mappings can be saved as reusable profiles. Applying a profile to another source compares observed label and context text and creates reviewable suggestions. Profiles do not silently approve mappings and do not use fixed pixel coordinates as their primary semantic rule.

## Strict stage separation

Action 20 only materializes ROI crops from confirmed mappings. It intentionally does not run value OCR. New mapped samples remain in `awaiting_value_recognition` until their ROI has been approved.

Action 21 recognizes only samples whose ROI status is `correct`. The output preserves the exact OCR string and adds parsing, unit extraction, range validation and separate OCR/mapping confidences. ROI review and value review remain independent.

## Database and compatibility

Training database schema v8 adds dedicated tables for detection sources, detected blocks, detected relationships, field definitions, field mappings and mapping profiles. Existing samples, ROI/value reviews, datasets, training runs, registered models and active model content are preserved during migration.

Existing 3.5.x workspaces can be opened directly. Run generic detection once to populate the new neutral detection layer, then create or confirm mappings before generating new ROI crops.

## Runtime boundary

The web labeler image remains lightweight. Generic mapping metadata is available to the UI, while OpenCV, NumPy and OCR-engine imports are deferred to the worker-side operations that actually crop or recognize images.
