# IsalaOCR 3.11.5

## Panel suggestions across preprocessing variants

- Panel Setup keeps plausible PP-Structure table regions from every full-image preprocessing variant, not only the globally selected run.
- Snap remains anchored to the user's rough rectangle and never jumps to a non-overlapping table.
- A rough panel is explicitly valid when no suggestion exists yet: save it, rerun Step 3, and the panel-specific PP-Structure result becomes available for later snapping.
- Selected-run and benchmark suggestions are deduplicated before rendering.
