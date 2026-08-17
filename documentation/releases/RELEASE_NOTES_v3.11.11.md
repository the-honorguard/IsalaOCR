# IsalaOCR 3.11.11

Reviewer UX cleanup for missing cells.

- Removed the reason/note modal before manually drawing a missing cell.
- The reviewer now enters draw mode immediately and stores `reason_code=other` automatically for a truly manual missing cell.
- Geometrically reconstructed cells keep their existing `table_geometry_error` metadata automatically.
- Esc cancels active drawing without leaving fullscreen review.
- Drawing can start over existing canvas layers, making fullscreen annotation less fiddly.
