# IsalaOCR 3.6.3

## Functionality, effectiveness and Mappingstudio UX review

Version 3.6.3 is a review release on top of the generic/Paddle workflow from 3.6.2. It does not introduce another workflow layer; it makes the existing one safer, more deterministic and faster to review.

### Mapping correctness

- Mappingstudio now treats **— niet mappen —** as an explicit removal instead of leaving an older mapping behind.
- Relation-form saves are validated and committed atomically. A bad field or relation can no longer leave a half-saved mapping set.
- One detected relation/value can no longer silently feed multiple functional output fields, including manual block mappings.
- Changing, reassigning or removing a mapping retires its previously materialized ROI sample. The stale sample is excluded from active review and recognition until **Mapping toepassen** creates the current ROI again.
- A fresh detection run now removes confirmed mappings that point to disappeared block/relation geometry instead of retaining hidden orphan mappings.
- Automatic mapping recalculation replaces the old suggestion set while preserving confirmed mappings.

### Paddle table effectiveness

- Full-page OCR remains the preferred text source for Paddle cells, but the PP-Structure internal OCR is now used **per missing cell** rather than only when the entire full-page OCR set is empty.
- OCR tokens are assigned to one best-fitting Paddle cell by geometric overlap, preventing duplicated text when cell boxes overlap slightly.

### Mappingstudio UX

- Added quick search across detected label, value and mapped field.
- Added source, status and confidence filters.
- Secondary/reference values remain hidden by default.
- Added a sticky live output preview with the full source image and separate label/value overlays.
- Added previous/next controls and `Alt+↑/↓` navigation through the currently visible relations.
- Added grouped functional-field selectors, direct duplicate-field warnings and disabled save buttons while duplicates exist.
- Only strong automatic suggestions (>= 82%) are preselected for bulk confirmation.

### Upgrade behavior

No database schema migration is required; schema remains **v9**. Existing data is preserved. When a stored mapping is changed after the upgrade, its old ROI is deliberately marked stale and must be recreated through **Mapping toepassen** before it can return to ROI/value review.
