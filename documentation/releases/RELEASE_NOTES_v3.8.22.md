# IsalaOCR 3.8.22 — writable PaddleDetection evaluation artifacts

PaddleX runs PaddleDetection training from the PaddleDetection source checkout. During inline COCO validation, PaddleDetection writes relative files such as `bbox.json` when no `output_eval` path is configured. The reusable trainer image keeps that source checkout root-owned while IsalaOCR runs as UID/GID 10001, so training could fail at the first validation pass with `PermissionError: [Errno 13] Permission denied: 'bbox.json'`.

v3.8.22 keeps the non-root security model and does not rebuild the heavy GPU image. The bind-mounted PaddleDetection compatibility module now installs a narrowly scoped file redirect when PaddleDetection imports its legacy `pkg_resources` dependency. For localization training only, known relative COCO evaluation artifacts (`bbox.json`, `mask.json`, `segm.json`, `keypoint.json`) are redirected to `<localization-run>/evaluation_artifacts/`. Reads of those exact relative names follow the same redirect so pycocotools evaluates the generated file. Absolute paths and unrelated file operations are unchanged.

Existing reviewed data, localization dataset, PaddleX validation, and GPU image can be reused. Retry GPU detector training directly after upgrading.
