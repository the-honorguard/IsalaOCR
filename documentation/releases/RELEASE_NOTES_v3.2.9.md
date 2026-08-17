# IsalaOCR Local v3.2.9

## PaddleX override argument fix

PaddleX accepts one configuration override per `-o` option. Earlier IsalaOCR
versions emitted a single `-o` followed by multiple override values. PaddleX
therefore parsed only the first override and rejected the remaining values as
unknown command-line arguments.

The training runtime now emits:

```text
-o Global.mode=check_dataset
-o Global.dataset_dir=/training/workspace/datasets/<dataset>
-o Global.output=/training/workspace/runs/check-<dataset>
```

The shared command builder is used for dataset validation, training,
evaluation and export. A regression test verifies that every override receives
its own `-o` flag.

This update does not alter DICOM input, collected crops, reviews, labels,
datasets, model files or the training database.
