# IsalaOCR 3.11.2

Table-first structure refinement. Step 2 now benchmarks several preprocessing variants with an optional automatic table-panel crop and selects the structurally strongest PP-Structure result. Step 3 adds Smart Fit, column normalization and explicit geometric reconstruction suggestions for missing cells. Table quality separates direct Paddle coverage from structurally reconstructed coverage and genuine manual fallback. The parked PicoDet detector remains untouched.
