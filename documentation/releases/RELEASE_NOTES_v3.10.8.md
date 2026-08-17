# IsalaOCR 3.10.8

This release repairs Step 5 visual detector diagnostics. Threshold **Bekijk** now loads the selected threshold, scrolls to the TP/FP/FN workbench, and shows the concrete error if loading fails. Ground truth and source images are resolved from the immutable COCO dataset associated with the evaluation so existing evaluation results cannot silently change when Detection Review is edited later.

The UI label **Direct akkoord** was also corrected: the stored `auto_accept_rate` is a strict reference-IoU match rate and does not account for unrelated false-positive output, so the UI now describes it as a strict reference match instead of implying that 100% of detector output can be accepted automatically.
