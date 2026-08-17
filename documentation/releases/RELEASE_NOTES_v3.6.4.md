# IsalaOCR 3.6.4

## Mapping feedback loop

Mappingstudio can now explicitly reject a detected label/value relation and store a structured reason. This is intended for detection errors such as a merged multi-row label, the wrong label/value pairing, an incorrect table row or column, bad ROI geometry, irrelevant data or duplicate detections.

A rejection is not stored as a free-text note only. The database stores a durable snapshot of the relation, a normalized pattern signature, the verdict, reason code and optional explanation. Confirmed mappings are stored as positive relation examples. This provides both positive and negative supervision for the IsalaOCR relation/mapping layer.

The feedback is used immediately in two ways:

- the rejected relation is removed from automatic suggestions and cannot be confirmed until the rejection is restored;
- future mapping suggestions are adjusted by a small feedback-aware relation-quality learner. Exact rejected patterns are suppressed; similar patterns are penalized according to the rejection reason and accumulated positive/negative evidence.

Feedback survives redetection through a normalized signature based on label text, value shape, context and coarse geometry rather than the transient relation ID. The same bad pattern on another source can therefore influence later suggestions.

This mechanism does **not** fine-tune PaddleOCR itself. PaddleOCR remains responsible for OCR/table structure. The learned layer is the IsalaOCR proposal/relationship layer that decides whether a detected label/value relation is a credible mapping candidate.

## UX

- Added **Afkeuren…** on every mapping relation.
- Added a modal with structured rejection reasons and an optional explanation.
- Added **Afkeuring herstellen** for accidental feedback.
- Rejected cards are visibly red, disabled for mapping and remain inspectable.
- Added a rejected-status filter.
- Added live feedback example counts.
- Rejected automatic-suggestion cards are removed from the current review UI immediately.
- The output preview warns when the selected relation is rejected.

## Data and migration

- Database schema increased from v9 to **v10**.
- New `mapping_relation_feedback` table stores durable positive/negative relation examples.
- Existing databases are backed up before migration using the existing schema migration mechanism.

## Validation

- 204 tests passed.
- 14 environment-dependent tests were skipped.
- New regression tests cover structured rejection, mapping removal, redetection persistence, cross-source feedback influence, positive examples and Mappingstudio controls.
