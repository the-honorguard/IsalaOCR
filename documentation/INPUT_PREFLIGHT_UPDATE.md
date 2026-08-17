# IsalaOCR v3.2.4 input preflight

Option 2 now checks the Windows-side input directory before Docker builds or starts.
It reports the project root, mounted host path, and number of processable files.
When the active project copy has no DICOM files, it also lists sibling IsalaOCR
project folders that still contain input files.

No DICOMs, models, crops, labels, or databases are included in this patch.
