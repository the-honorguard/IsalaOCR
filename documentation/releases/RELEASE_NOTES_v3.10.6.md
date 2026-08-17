# IsalaOCR 3.10.6

## Step 4 layout fix

- Restored the visual 1/2/3 sub-step markers in Dataset & detector trainen so phase headings use the intended two-column layout.
- Changed phase cards to flex-column layout so primary actions remain aligned at the bottom without empty grid rows.
- GPU and CPU training actions now share one prerequisite explanation instead of rendering the same long blocker twice.
- Training buttons use equal-width columns and collapse to one column on narrow screens.
- Docker build progress uses an ASCII separator to avoid mojibake in Windows/JSON/browser output.
