# IsalaOCR 3.9.5

Local, privacy-conscious OCR and model-training tooling with **isolated projects**. Start the integrated control panel with `START.cmd`.

IsalaOCR 3.9.5 stabilizes the interactive WebUI. Dataset/training, evaluation/quality and data/model management update component state without full-page reloads. The clients use short JSON polling instead of Server-Sent Events, are compatible with the bundled React 16 runtime, and fail visibly through error boundaries instead of leaving an empty screen. User-facing migration/implementation banners have been removed.

## Project model

The application/tooling is generic; datasets, mappings and trained models may be intentionally use-case specific. Select the active project in the sidebar before running a workflow. Each project owns its detection/review database, localization datasets/models/evaluations/gate, field mappings, recognition data/model registry and extracted project output. Shared Paddle/PaddleX caches and Docker infrastructure remain global.

Use-case templates live under `application/config/use_cases`. The migrated/default testcase is `philips_cmr_volume_results`; a generic empty template is also included. New projects default to an isolated `/input/projects/<project-id>` source folder, while the migrated first project keeps `/input` for compatibility.

## Pipeline A — Field Detection & Crop Geometry

Pipeline A answers **where are the crops?** In the current v3.11 table-first experiment, PP-StructureV3 table/cell geometry is measured on its own. Loose OCR/text boxes and the active PicoDet field detector are deliberately not merged into the primary candidate pass; the detector workflow is preserved only as a parked fallback.

Detection Review is exception-first. The bottom review dock has four decisions:

- **Includeren**: desired crop with usable geometry.
- **Niet relevant**: detected region that should not be a target for this project.
- **Incorrect**: detector error; an optional reason can describe the geometry failure.
- **Kader aanpassen**: correct the bounding box and save that geometry as positive ground truth.

`Rest standaard includeren` is enabled by default. When an image is marked **✓ Afbeelding klaar**, remaining open ROI candidates are included automatically unless that option is disabled. Review writes are queued per ROI so the reviewer can continue immediately.

Only source images explicitly marked **✓ Afbeelding klaar** are eligible for localization training. Incomplete images are excluded completely, even when individual ROI decisions already exist. The dataset page previews the exact included/excluded images and ROI counts before COCO generation.

Localization artifacts are retained independently. **Data & modellen** can keep and inspect multiple datasets, detector runs/models and evaluations. The evaluation dataset, detector under test and historical comparison pair are explicit selections. The active detector is a separate state. Generated artifacts can be deleted from the UI with dependency checks; the current work dataset and active detector are protected.

## Pipeline B — Value Mapping & OCR

Pipeline B stays locked behind the active project's current geometry gate. In table-first mode this is the TABLE-FIRST CHECK derived from explicit cell review; in legacy/fallback detector mode it remains the Detection Gate. Mapping assigns semantic meaning to Pipeline-A geometry, final crops are materialized, values are recognized/reviewed, and recognition datasets/models are trained and registered inside the project context.

Already queued worker jobs are pinned to the project that queued them, so switching the UI project does not redirect a running job.

See `documentation/START_HERE.md` and `documentation/releases/RELEASE_NOTES_v3.9.5.md`.

## v3.8.4 preparation split

Stap 1 is Voorbereiding. Vanuit die pagina kun je alles in één keer voorbereiden of elk ontbrekend onderdeel afzonderlijk downloaden/bouwen. Interne taak-ID’s worden niet als workflowstappen weergegeven.
