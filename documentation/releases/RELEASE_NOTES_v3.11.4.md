# IsalaOCR 3.11.4

## Panel Snap respects the user-drawn region

- `Snap naar Paddle-regio` now treats the rough manual panel as authoritative.
- Only Paddle table-region suggestions that overlap the selected manual panel are eligible for snapping.
- Candidate ranking uses IoU, overlap coverage and centre proximity within the overlapping candidates.
- If no suggestion overlaps the panel, the UI keeps the manual panel unchanged and explains what to do instead of jumping to another table.
- This prevents an LV panel from snapping to an RV suggestion (or vice versa) simply because that region had a stronger global score.
