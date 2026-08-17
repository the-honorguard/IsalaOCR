# IsalaOCR v3.4.2

## Dataset preflight recovery

The dataset preflight no longer reduces every pointer or compatibility problem to
"run option 7". It now:

- strips a possible UTF-8 BOM from `training/workspace/datasets/latest.txt`;
- validates the exact required files and reports missing filenames;
- searches existing dataset directories for the newest complete grouped dataset
  when `latest.txt` is missing, stale, invalid, or points to an incomplete folder;
- repairs `latest.txt` without rebuilding or modifying labels;
- treats `characters.txt` as optional audit metadata because option 8 derives the
  character set directly from the verbatim labels in `train.txt`, `val.txt`, and
  `test.txt`;
- requires `dict.txt` only for training and explains that option 8 creates it from
  the pinned official PP-OCRv6 dictionary.

## Null-safe GPU and Docker checks

Windows PowerShell 5.1 can occasionally return an empty or incomplete redirected
process result. The GPU preflight, workspace doctor, Docker image inspection, and
Compose diagnostics now handle null output, timeouts, and absent exit codes
without throwing `You cannot call a method on a null-valued expression`.

Unexpected checker exceptions are converted to explicit failed check rows. No
training action is started when its checker cannot finish reliably.

## Compatibility

The reusable training image revision remains `3.3.11`. Installing this release
does not require the CPU or NVIDIA images to be downloaded or rebuilt.
