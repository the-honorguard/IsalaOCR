# IsalaOCR 3.12.0

## Table-cell learning loop

Reviewed table geometry can now be converted into a project-specific COCO table-cell dataset and used to fine-tune PaddleX `RT-DETR-L_wireless_table_cell_det`. The trained model is registered per project and can be activated for subsequent PP-StructureV3 table runs.

### Workflow
1. Complete table-cell review.
2. Build and validate the table-cell dataset in Step 6.
3. Train on GPU (recommended) or CPU.
4. Review validation recall/precision/F1 and false positives per panel.
5. Activate the model.
6. Rerun Step 3 and compare direct Paddle coverage / manual correction load.

Datasets carry a review fingerprint; after review geometry changes the old dataset is marked stale and must be rebuilt before training.
