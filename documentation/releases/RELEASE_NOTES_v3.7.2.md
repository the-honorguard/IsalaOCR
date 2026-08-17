# IsalaOCR 3.7.2 — Detection scope separation

## Geometry and relevance are now independent

Detection Review no longer treats every technically correct box as either positive ground truth or a false positive. Each candidate has two independent decisions:

1. **Geometry** — correct, adjusted or detection error.
2. **Extraction scope** — relevant or not relevant for the current OCR workflow.

A date, UI control, graph annotation or other correctly localized element can therefore be marked **Not relevant** without teaching the localization detector that the box itself is wrong.

## Training semantics

Relevant reviewed boxes are stored as positive `field_roi` ground truth. Technically correct but out-of-scope boxes are stored with training role `ignore`. The COCO dataset writes these regions with `iscrowd=1` and `ignore=1`, so they are not intentionally converted into background/false-positive supervision.

Detector evaluation also suppresses predictions that substantially overlap an ignore region. This prevents a detector from losing precision merely because it correctly found an element that this extraction profile does not need.

## Pipeline B

Out-of-scope geometry is excluded from Mapping Studio and from final ROI resolution. Only relevant Pipeline-A geometry is allowed to become a value mapping/crop.

## Database

Schema version is **12**. Existing v3.7.1 databases are migrated automatically. New columns preserve relevance status/reason and the localization training role. A SQLite-consistent backup is made before migration.

## UI

Detection Review Studio now has separate **Geometry** and **Relevance for this OCR** sections. A quick **Not relevant** action marks a pending candidate as geometrically correct but out of scope, after selecting a structured reason such as date/time, UI element, reference value, graph annotation or technical overlay.

The heavyweight training-image revision remains **3.7.0**; this release does not add Python/Docker dependencies.
