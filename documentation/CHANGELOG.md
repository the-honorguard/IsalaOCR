## 3.14.0 - 2026-08-14

- Table-cell training is nu expliciet versioned: Ground Truth, dataset, trainingsrun, model, Stap-3 detectierun en Stap-7 review hebben gescheiden identiteiten.
- Stap 3 schrijft per complete run een `detection_batch_id` en het daadwerkelijk gebruikte table-cell model/run/dataset weg.
- Stap 7 gebruikt uitsluitend die bevroren detectiemetadata; activatie van model v2 kan oude v1-predictions niet meer als v2-data herlabelen.
- Als het actieve model nieuwer is dan de laatste detectie blokkeert Stap 7 en vraagt om opnieuw detecteren; oude runs blijven alleen historie.
- Alleen de nieuwste detectierun is schrijfbaar; historische runs zijn read-only en oude reviewbeslissingen worden nooit naar een nieuwe run overgenomen.
- Een volledig afgeronde Stap-7-review wordt trainingsfeedback: alleen `Model fout` wordt hard-example input (FP/FN/geometrie x3, merged x4), uitsluitend in TRAIN.
- `Functioneel correct` wordt niet bestraft; VAL en TEST blijven ongewijzigd.
- Dataset-currentness omvat nu zowel GT als de nieuwste afgeronde reviewfeedback, zodat een nieuwe reviewronde de volgende dataset/training werkelijk kan veranderen.
- Vervolgtraining gebruikt waar mogelijk de checkpoint van het actieve custom model met lagere learning rate en 40 standaard continuation-epochs; veilige fallback naar de officiële pretrain blijft bestaan.
- Modelmetadata bewaart parent-model, training mode, learning rate en epochs; Stap 6 toont de correcte volgende actie in de iteratieve lus.

## 3.13.10 - 2026-08-14

- Canonieke Ground Truth heeft nu een persistente **reviewstatus per bronafbeelding**, onafhankelijk van de actuele Stap-3 detector-run.
- In Stap 4 GT-modus is **GT-afbeelding gecontroleerd** weer expliciet beschikbaar en kan die status ook opnieuw worden geopend.
- Een nieuwe detector-run reset niet langer de GT-controle en honderden nieuwe predictions worden niet meer ten onrechte als open Stap-4 kandidaten meegeteld; modelpredictions horen na canonieke GT in Stap 7.
- Bestaande canonieke GT uit v3.13.1–v3.13.9 migreert veilig als reeds gecontroleerd, zodat een upgrade niet alle eerder afgewerkte bronnen opnieuw openzet.
- Toevoegen, verplaatsen/resizen of verwijderen van een GT-cel opent alleen de betreffende bron opnieuw voor GT-controle.
- Stap 6 blokkeert datasetbouw zolang een gewijzigde GT-bron nog niet opnieuw als gecontroleerd is gemarkeerd.
- Alleen de reviewstatus wijzigen verhoogt de GT-geometrierevisie niet en maakt een dataset dus niet onnodig verouderd.

## 3.13.9 - 2026-08-14

- Stap 7 koppelt een lage-IoU prediction die ≥95% van precies één GT-cel afdekt nu alsnog één-op-één aan die GT.
- Zo wordt een oversized maar inhoudelijk gekoppelde detectie niet langer dubbel als `Extra detectie (FP)` + `GT-cel gemist (FN)` weergegeven, maar als één `Geometrie afwijkend`-item.
- De bestaande keuze `Functioneel correct ✓` is daardoor ook beschikbaar voor deze containment-gevallen zonder de canonieke GT te verruimen.
- Predictions die meerdere GT-cellen substantieel afdekken blijven `Merged cells` en worden niet door de fallback gered.
- Bestaande evaluator-v1 vergelijkingsruns worden bij het openen in-memory met de nieuwe matchingsemantiek bekeken; opnieuw detecteren is niet nodig en de bevroren raw runbestanden worden niet herschreven.

## 3.13.8 - 2026-08-14

- Stap 7 kent nu een derde geometrie-oordeel: **Functioneel correct ✓** voor predictions die niet strak genoeg zijn voor de IoU-grens maar downstream wel bruikbaar zijn.
- Functioneel-correct laat de canonieke Ground Truth ongewijzigd en wordt apart als `functional_ok` opgeslagen in plaats van als modelmisser.
- Geometrie-afwijkingen tonen naast IoU nu **GT-dekking** en **extra prediction-oppervlak**.
- Niet-bindende hint **waarschijnlijk bruikbaar** bij ≥95% GT-dekking en ≤30% extra prediction-oppervlak; inhoudelijke beoordeling blijft handmatig.
- Bestaande Stap-7-runs worden bij het tonen verrijkt met deze metrics, zonder frozen runbestanden te herschrijven.
- Server-side validatie voorkomt dat FP/FN/merged-issues als functioneel correct worden afgesloten.

## 3.13.7 - 2026-08-14

- Initiële Stap-4-review toont standaard alleen nog open kandidaten; reeds beoordeelde kaders verdwijnen direct uit zowel de rechterlijst als de canvas-overlay.
- Nieuwe knop **Toon beoordeelde** / **Beoordeelde verbergen** maakt reviewed kandidaten tijdelijk opnieuw zichtbaar zonder reviewdata of Ground Truth te wijzigen.
- Verborgen reviewed kandidaten worden uitgesloten van klik-/sleepselectie, zodat ze niet per ongeluk opnieuw in batchacties terechtkomen.
- Volledig afgeronde bronafbeeldingen zijn standaard verborgen in het initiële reviewoverzicht; **Toon afgeronde reviews** brengt ze terug.
- Vorige/volgende-bronnavigatie slaat afgeronde bronnen over zolang afgeronde reviews verborgen zijn.
- Deze zichtbaarheid geldt alleen voor de initiële review; canonieke Ground Truth in Stap 4 blijft volledig zichtbaar en bewerkbaar.

## 3.13.6 - 2026-08-14

- Stap 7: afwijkingskaders links zijn nu klikbaar; de exact gekoppelde afwijking rechts wordt persistent gemarkeerd en automatisch in beeld gescrold.
- De reverse highlight gebruikt dezelfde `issue_id`-koppeling als de bestaande hover-highlight, inclusief geometrie/merged-koppelingen met meerdere relevante kaders.
- Als een aangeklikt kader door het huidige filter verborgen is, schakelt Stap 7 naar `Alle afwijkingen` zodat de gekoppelde rij direct zichtbaar wordt; `Alleen open` blijft na een reviewactie normaal items direct verbergen.
- Keyboardbediening toegevoegd: Enter/spatie selecteert een kader, Escape wist de vaste selectie.

## 3.13.5 - 2026-08-14

- Stap 7: hover/focus op een afwijking highlight het exacte bijbehorende prediction-/GT-kader boven alle overlays.
- Stap-7 reviewacties worden in-place via AJAX opgeslagen; geen paginarefresh of scrollsprong meer bij bevestigen, GT-controleren, wissen of direct aan GT toevoegen.
- Open/beoordeeld-tellers en oordeelbadges worden direct in de DOM bijgewerkt.
- Worker-backed workflowacties verversen de pagina automatisch na succesvolle afronding zodat nieuw vrijgekomen vervolgknoppen direct zichtbaar zijn.
- Scrollpositie blijft behouden over deze doelbewuste worker-completion refresh.

## 3.13.4 - 2026-08-14

- Stap 7: `Extra detectie (FP)` kan nu rechtstreeks met **+ Toevoegen aan GT** aan de canonieke Ground Truth worden toegevoegd.
- Prediction-geometrie wordt server-side van panelcoördinaten naar volledige broncoördinaten omgerekend.
- Dubbelklikken/herhalen maakt geen dubbele GT-cel; een bestaande vrijwel identieke GT-cel wordt herkend.
- Directe GT-toevoeging sluit het vervolg-reviewissue af als `gt_added` en maakt de bestaande table-cell dataset bewust verouderd.
- Geometrie aanpassen/verwijderen blijft exclusief in Stap 4, zodat modelreview en GT-beheer gescheiden blijven.

## 3.13.3 - 2026-08-14
- Toon bij alle worker-backed workflowknoppen een geschatte doorlooptijd als compacte range.
- Centrale duration-map voor alle huidige en legacy action IDs, inclusief cache/hardware-toelichting.
- Kleine technische checkknoppen houden alleen een tooltip zodat voorbereidingstabellen compact blijven.

## 3.13.2 - 2026-08-14
- Stap 4 GT-review: expliciete Vorige afbeelding / Volgende afbeelding knoppen blijven zichtbaar in fullscreen.
- Alt+← / Alt+→ blijven beschikbaar als sneltoetsen.

## 3.13.1 - 2026-08-14

- Stap 4 wordt na de eerste table-cell dataset een persistent **Ground Truth beheer**-scherm.
- Nieuwe Stap-3 detector-runs overschrijven of heropenen de canonieke GT niet meer.
- Canonieke GT wordt bij upgrade automatisch uit de laatste table-cell dataset gereconstrueerd.
- GT-cellen kunnen in Stap 4 worden toegevoegd, verplaatst/resized en verwijderd.
- Stap 6 bouwt volgende table-cell datasets uit de canonieke GT, onafhankelijk van actuele predictions.
- Stap 7 blijft verantwoordelijk voor vergelijking/review van nieuwe detector-runs.

## 3.13.0 - 2026-08-14

- Nieuwe Stap 7: Modelvergelijking & vervolg-review.
- Stap 4 blijft de initiële/canonieke Ground Truth-fase; nieuwe Stap-3-runs overschrijven die referentie niet.
- De table-cell trainingsdataset fungeert als bevroren GT-snapshot voor modelvergelijkingen.
- Oorspronkelijke Stap-4 machinegeometrie wordt als Model 0 gereconstrueerd.
- Complete Stap-3-runs worden afzonderlijk gearchiveerd en standaard met de vorige run vergeleken.
- Vergelijking toont precision/recall/F1, TP/FP/FN, directe geometrie, afwijkende geometrie en merged-cell gevallen.
- Alleen verschillen komen in de vervolg-review; modelreview is run-scoped en wijzigt Ground Truth niet automatisch.
- Mapping/OCR-flow schuift één stap door: Mapping Studio is nu Stap 8 en recognition-activatie Stap 16.

## 3.12.3 - 2026-08-14

- Made table-cell model registration safe on Docker Desktop/Windows bind mounts by copying inference bytes without POSIX metadata preservation.
- Added recovery of completed, evaluated but unregistered table-cell runs so a registration failure does not repeat 120 training epochs.
- Kept activation explicit and fail-closed.

## 3.12.2 - 2026-08-14
- Fixed table-cell fine-tuning failing at the first inline validation pass with `PermissionError: bbox.json`.
- Reused the bounded PaddleDetection compatibility redirect so relative COCO evaluation artifacts are written inside the writable table-cell run directory.
- Added regression coverage for the normal non-root training runtime and stale redirect cleanup.

## 3.12.1 - 2026-08-14

- Hotfix: workflow overview is null-safe when table-first mode has no active trained table-cell model yet.
- Prevents `AttributeError: 'NoneType' object has no attribute 'get'` before first table-model activation.

## 3.12.0 - 2026-08-13
- Added the reviewed table-cell learning loop: build/validate COCO panel datasets, fine-tune RT-DETR-L wireless table-cell detection, register/activate the project model, then rerun table detection.
- Active project table-cell models are injected into PP-StructureV3 through `wireless_table_cells_detection_model_dir`.
- Table-cell datasets are fingerprinted against current review geometry so stale datasets cannot silently be trained after review changes.
- Added a dedicated Step 6 · Tabelmodel verbeteren with prerequisite explanations and validation metrics.

## 3.11.13 - 2026-08-13

- Handmatig toegevoegde table-cellen zijn opnieuw selecteerbaar, resizebaar en verwijderbaar vanuit de reviewcanvas.
- Handmatige kaderwijzigingen worden persistent opgeslagen via een aparte PATCH-route.
- Selectienummers/bolletjes staan in een aparte always-on-top overlaylaag zodat overlappende kaders betrouwbaar gekozen kunnen worden.
- Reviewregel verduidelijkt: één kader = één functionele cel; merged multi-row/multi-cell detecties afkeuren en de echte cellen apart toevoegen.

## 3.11.12 - 2026-08-13

- Moved `+ Ontbrekende cel` next to the primary review decisions in the persistent reviewer dock.
- The action no longer lives in the generic canvas toolbox and remains available when fullscreen Tools are collapsed.
- Direct draw behavior and automatic provenance from 3.11.11 are unchanged.

## 3.11.11 - 2026-08-13

- Removed the redundant "Ontbrekend veld toevoegen" modal from the Table Cell Reviewer.
- `+ Ontbrekende cel tekenen` now enters drawing mode immediately; provenance/reason metadata is assigned automatically.
- Drawing mode works in fullscreen/focus mode and can be cancelled with Esc.
- Manual drawing can start directly over the canvas overlays instead of requiring an empty background pixel.

## 3.11.10 - 2026-08-13

- Fixed reconstructed-cell `+` actions in the Table Cell Reviewer: canvas marquee selection no longer captures the pointer gesture.
- Reconstructed suggestions now sit above candidate geometry and provide explicit success/error feedback when converting a proposal into a positive manual cell.
- Newly added manual annotations return explicit provenance/training-role metadata so the reviewer labels them correctly without a page refresh.

## 3.11.9 - 2026-08-13

- Fullscreen Table Cell Reviewer gebruikt voortaan een compacte, standaard ingeklapte toolbox rechtsboven.
- Geavanceerde reviewacties openen alleen via `Tools`, zodat de viewer niet meer door een brede toolbar wordt afgedekt.
- De compacte toolbox kan tussen boven- en onderzijde worden gedockt.

## 3.11.8 - 2026-08-13

- Updated Table Cell Review Studio with viewport-filling fullscreen/focus mode.
- Floating review, zoom and optional inspector toolboxes keep the source image large while retaining Smart Fit and review actions.
- Added previous/next source navigation to the reviewer.

## 3.11.7 - 2026-08-13

- Panel Setup viewer can switch to a viewport/native fullscreen focus mode.
- The same editor state is reused in focus mode; drawing and resize handles stay active.
- Controls become a floating toolbox and the panel list becomes an optional floating overlay.
- Added previous/next source navigation for quickly validating the project panel profile on multiple images.
- Unsaved geometry changes are protected before source navigation.

## 3.11.6 - 2026-08-13

- Added one-time project panel-name setup to Step 1; Step 2 reuses these names instead of asking for them again.
- Added eight drag handles to resize snapped/manual table panels before saving.
- Panel geometry can be cleared without deleting the project-wide panel names.
- Panel definition changes are tracked separately and invalidate prior table results when semantic panel identity changes.

## 3.11.5 - 2026-08-13

- Panel Setup now preserves table-region suggestions across all preprocessing variants and explains that a rough panel can be saved/run even before an exact Paddle suggestion exists.

## 3.11.4 - 2026-08-13

- Panel Setup: `Snap naar Paddle-regio` only considers Paddle regions that overlap the user-drawn panel.
- Non-overlapping table regions can no longer steal the snap target; no-match now produces an explicit UI message.
- Snap ranking now prioritizes user-panel overlap/IoU before centre distance.

## 3.11.3 - 2026-08-13

- Added user-controlled project-level table panel setup.
- Runs preprocessing and PP-Structure independently per saved panel.
- Parks automatic panel focus as bootstrap/suggestion behavior only.
- Invalidates stale table review results after panel-profile changes.
- Added panel drawing, Paddle-region snapping and multi-panel workflow support.

## 3.11.2 - 2026-08-13

- Added table preprocessing benchmark: original, grayscale, CLAHE, inverted CLAHE and adaptive threshold variants.
- Added automatic result-panel crop when the initial PP-Structure pass yields a trustworthy table region.
- Added structural scoring based on row regularity, column alignment, usable cell density and overlap.
- Added Smart Fit/Magic Wand review action that snaps cells to inferred row/column boundaries.
- Added column normalization and conservative missing-cell reconstruction suggestions.
- Table quality now distinguishes direct Paddle coverage, geometrically reconstructed coverage and truly manual fallback.

## 3.11.1 - 2026-08-13

- Stap 1 vereenvoudigd tot een duidelijke table-pipeline readiness-status.
- Table-first voorbereiding telt alleen de vereiste inference/table-component.
- Installatie- en herstelacties verplaatst naar een ingeklapt onderhoudsblok.

## 3.11.0 - 2026-08-13

- Switched the primary localization workflow to table-first PP-StructureV3 geometry.
- Stopped mixing loose OCR text boxes and the active PicoDet field detector into Step 2.
- Added explicit table-cell review and a TABLE-FIRST CHECK based on direct coverage, box adjustments, rejected cells and manually added missing cells.
- Parked the previous field-detector dataset/training/evaluation/activation pages without deleting existing artifacts.
- Made Mapping Studio depend on table-first geometry quality while preserving the legacy detector gate for fallback mode.
- Reduced preparation requirements for the table-first experiment to the inference OCR/table component.

## 3.10.11 - 2026-08-12

- Replaced the broad post-training detector evaluation screen with a TRAIN → VALIDATION → root-cause → final TEST decision pipeline.
- Confidence calibration is validation-driven; TEST is held back until validation produces a production candidate.
- Added automatic root-cause classification and a single recommended next action.
- Added split/IoU/FP-cause controls and moved raw metrics into advanced diagnostics.
- Added in-UI explanations for detection metrics.
- Fixed Step 5 detector resolution to use the persisted model ID and run registration metadata.

## 3.10.9 - 2026-08-12

- Fixed Step 5 visual diagnostics in the lightweight labeler image.
- Moved IoU/greedy matching into dependency-light detection_gate.py so diagnostics no longer import the heavy localization module at request time.
- Added regression coverage for the labeler runtime without isala_ocr.training.localization.

## 3.10.8 - 2026-08-12

- Fixed Step 5 threshold `Bekijk` actions so they always navigate to the visual diagnosis and surface backend errors instead of appearing inert.
- Visual TP/FP/FN diagnosis now uses the frozen COCO dataset and dataset image that belonged to the evaluation, rather than mutable live review rows.
- Added a dedicated frozen-dataset image endpoint for evaluation overlays.
- Renamed the misleading `Direct akkoord` presentation to a reference-match metric and clarified that it does not mean all detector output is automatically acceptable.

## 3.10.7 - 2026-08-12

- Add visual TP/FP/FN diagnostics to Step 5 with overlays on the original test renders.
- Classify false positives as duplicates, localization/IoU errors, negative-region detections or unmatched detections.
- Allow an unmatched red detection to be explicitly confirmed as missing ground truth; the dataset/evaluation is then marked stale by the existing review workflow.
- Make confidence-sweep rows directly visualizable and extend the sweep through 0.95 for high-FP calibration.
- Add plain-language guidance explaining how to distinguish missing labels, threshold/NMS issues and model errors.


## 3.10.6 - 2026-08-12

- Fixed Step 4 phase-card CSS/layout regression.
- Restored numbered phase headings and equal-width training actions.
- Deduplicated disabled training prerequisite text.
- Avoided mojibake in Docker build progress labels.


## 3.10.5 - 2026-08-12

- Fix Step 4 React crash on incomplete/legacy validation payloads.
- Normalize readiness warnings/errors/totals so existing project state cannot crash the React workbench.
- Harden preview/source rendering against missing optional fields.
- Show the actual client-side exception if a React render still fails, instead of incorrectly suggesting a webinterface restart as the only remedy.
## 3.10.4 - 2026-08-12

- Add human-readable dataset/model names with project, date and time while preserving stable technical IDs.
- Show explicit prerequisite/blocker explanations beside disabled workflow buttons, including the next step required to unlock them.
- Surface worker, dataset validation, split freshness and Detection Gate requirements before actions are started.

## 3.10.3

- Centralize Docker image existence checks in `Get-DockerImageState` so preparation/install/status use the same result logic.
- Accept a valid `sha256:` image ID as authoritative when Windows PowerShell 5.1 temporarily exposes a null Docker process exit code.
- Retry freshly built training-image inspection briefly to avoid false "Required Docker image is missing" failures immediately after successful BuildKit export.
- Keep download readiness separate from install/build validation; no model redownload is triggered when downloads are already complete.
- Add regression coverage preventing direct ad-hoc `docker image inspect` checks from returning to the preparation orchestrator.

## 3.10.2

- Cache project catalog/active-project metadata by file signature instead of rereading JSON throughout every page request.
- Cache registry state and derived Detection Gate state across requests while keeping authoritative gate checks at workflow boundaries.
- Replace fixed high-frequency WebUI polling with adaptive polling: fast during active jobs, slower while idle and much slower in hidden tabs.
- Filter and cache job-status JSON before sorting/log inspection so the activity dock and React workbenches no longer repeatedly parse the entire job history.
- Replace per-source detection review queries with grouped SQLite aggregates and reuse those aggregates across overview pages.
- Preload Pipeline-A annotations/candidates once per source in Mapping Studio instead of querying the same geometry for every relation.
- Reuse decoded source renders for concurrent crop requests and lazy/async-load offscreen crop images.
- Cache artifact directory-size calculations briefly instead of recursively walking run trees on every artifacts refresh.
- Remove full pipeline-snapshot dependencies from localization readiness/quality payloads and reuse already-calculated route state.
- Scan recognition evaluation artifacts once per overview render for both baseline and custom results.
- Add interface-performance regression coverage for project metadata caching, bulk review counts, adaptive polling, lazy image loading and query-free preloaded mapping resolution.

## 3.10.1

- Pin every queued WebUI job to the project that created it by routing the legacy `/jobs` endpoint through the canonical queue helper.
- Redirect the obsolete `/models` screen to the current Projecten & modellen management UI so stale action IDs cannot start unrelated preparation jobs.
- Cache the active project `TrainingDatabase` instance and skip full schema initialization when SQLite `user_version` is already current.
- Roll back SQLite transactions on exceptions instead of committing partial work.
- Aggregate mapped-sample status directly in SQLite instead of loading up to 100,000 rows into Python.
- Slim the frequently-polled `/api/status` endpoint to queue/worker/active-model state only.
- Move recursive model-cache inventory into the host preparation refresh and read its counts from `preparation_status.json`.
- Make preparation auto-refresh reusable after a fresh snapshot and retry after failed inventory queueing/checks.
- Reduce activity-dock status polling frequency from 1.5 s to 2.5 s.
- Add regression coverage for schema fast-path, rollback behavior, mapped-sample aggregation, project-pinned jobs and the legacy models redirect.

## 3.10.0

- Preparation status is now freshness-aware: an old `preparation_status.json` can no longer keep the UI falsely green after Docker images are removed.
- Step 1 polls a lightweight preparation API and automatically queues one host inventory refresh when the status snapshot is stale.
- Preparation phase status updates in-place without a full page reload.
- Failed preparation checks always refresh the host status snapshot in a `finally` path.
- `Alles controleren` now checks every preparation component and reports all failures together instead of stopping at the first missing image.
- Clarifies the split between `isalaocr-training-gpu` (OCR recognition) and `isalaocr-training-gpu-detection` (PicoDet field detector).

## 3.9.9
- Add an automatic small-dataset PicoDet-S training profile: batch 2, 150 epochs, LR 0.005, warmup 20 and evaluation every 5 epochs for <=32 independent train images.
- Run a two-image sanity-overfit check before full small-dataset training and abort early when the trained sanity model still produces zero predictions at confidence 0.01.
- Persist `training_config.json`, requested overrides and the generated PaddleDetection config in every localization run.
- Surface the effective training profile and estimated optimizer-step count in Step 4.
- Keep the heavy training image revision at 3.8.4 because the localization runtime remains host-mounted.

## 3.9.8
- Merge project management and data/model management under one Projecten & modellen menu entry.
- Keep the legacy management routes as redirects/tabs for compatibility.

## 3.9.7
- Queued artifact deletion through the existing web worker.
- Live pending/running deletion state in Data & modellen.
- Worker-side revalidation for dataset/model/evaluation/run deletion.

## 3.9.6

- Fixed dataset/model artifact deletion so conflicts remain visible instead of disappearing on the next status poll.
- Current work datasets can now be deleted safely by switching to another retained dataset first.
- Cascade-delete failures are no longer swallowed; active-model dependencies remain hard-blocked.
- Added explicit success feedback after dataset/model/evaluation/run deletion.

## 3.9.5

- Fixed React 16 invariant 130 on localization quality pages.
- Replaced WebUI SSE/EventSource updates with lightweight component polling.
- Removed automatic page reloads from interactive localization screens and Detection Review manual annotations.
- Added frontend error boundaries.
- Cleaned user-facing migration/React/SSE labels and duplicate status/task UI.
- Renamed artifact management to Data & modellen.

## 3.9.4

- Fix Detection Gate `ModuleNotFoundError` in the lightweight WebUI container.
- Separate pure gate-threshold logic from the OpenCV/OCR localization module.
- Add labeler-container dependency regression coverage.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.9.3

- Merged detector evaluation and comparison into Step 5.
- Added explicit dataset/model/evaluation selection and artifact deletion management.
- Fixed React 16 compatibility for quality pages stuck on loading.
- Made Detection Gate derivation ignore alternate-dataset evaluations.
- Renumbered the remaining pipeline to 17 user-facing workflow steps.

## 3.9.2

- Prevent derived Detection Gate calculation errors from crashing the global web UI context.
- Keep Pipeline B fail-closed when gate derivation fails and expose a diagnostic reference instead.
- Add persistent `webui_errors.log` traceback logging and a useful local 500 error page.
- Reuse the gate state already calculated by the quality payload instead of recomputing it twice.

## 3.9.1

- Added current ground-truth/split fingerprints to trained localization evaluations and activation checks.
- Replaced stale Detection Gate messaging with derived states: open, failed, awaiting activation, stale or not evaluated.
- Added low-threshold (0.01) trained inference plus 0.01–0.50 confidence sweeps on train/validation/test.
- Step 5 can re-evaluate the latest existing trained model without retraining.
- Migrated detector evaluate/compare/activate/report screens to React + REST + SSE with no full-page refresh.

## 3.9.0

- Start the incremental React/TypeScript frontend migration with Step 4 (dataset build, validation and detector training).
- Add canonical REST endpoints for the localization workbench, split mutations and reactive job submission.
- Add a Server-Sent Events invalidation stream so Step 4 updates component state without full-page refreshes.
- Keep the Python backend, worker queue, Docker/PaddleX training runtime and existing workflow pages intact during migration.
- Package the compiled frontend and local React runtime in the lightweight labeler image; no Node.js runtime or CDN is required.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.8.22

- Redirect PaddleDetection COCO evaluation artifacts (`bbox.json`, etc.) to the writable localization run directory during training.
- Preserve non-root UID/GID 10001 and the reusable GPU training image; no heavy image rebuild is required.
- Keep inline validation enabled so training still produces validation metrics while avoiding writes to the read-only PaddleDetection source checkout.

## 3.8.21

- Fix PicoDet-S GPU training on environments where setuptools no longer exposes legacy `pkg_resources`; a bounded compatibility module is injected only into PaddleDetection subprocesses.
- Explicitly propagate the mounted localization runtime through `PYTHONPATH` to nested PaddleX/PaddleDetection commands, so existing heavy GPU images can be reused without rebuilding.
- Strengthen PaddleDetection runtime verification by importing `ppdet.model_zoo.model_zoo`, the exact path that previously failed.
- Make Step 4 validation readiness update live when the validation job finishes; GPU/CPU training buttons are enabled without a manual browser refresh.
- Emit job lifecycle events from the shared activity dock so workflow pages can react to completed local jobs without opening the terminal.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.8.20

- Fixed localization training readiness drift by making `localization_datasets/latest.txt` the canonical current-dataset pointer in both UI and preflight.
- Validation now writes a dataset-bound `training_ready.json` only after IsalaOCR and PaddleX both succeed.
- Step 4 and training preflight now show the exact current `loc-*` dataset ID and validation state.
- Existing pre-3.8.19 valid datasets remain accepted through their concrete validation reports; revalidating adds the canonical marker.

## 3.8.18

- Merged former workflow steps 4, 5 and 6 into one **Dataset & detector trainen** workbench.
- Fixed detector-training preflight reading PaddleX validation markers: `status: ok` is now accepted and new markers also contain `ok: true`.
- Step 4 now shows build, IsalaOCR/PaddleX validation, split freshness and GPU/CPU training together.
- Legacy `/process/localization-validate` and `/process/localization-train` URLs redirect to the merged Step 4 page.
- Renumbered the remaining visible workflow steps to a contiguous 1-18 sequence; internal action IDs are unchanged.

## 3.8.17

- Make the bottom activity dock progress-first: compact by default and no automatic terminal expansion when jobs start.
- Keep task title, status and a small progress bar visible while the terminal is collapsed.
- Move terminal expansion to an explicit user action and migrate away from the legacy auto-open preference.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.8.16

- Step 4 localization split controls: safe automatic counts and per-source overrides.
- 14 completed images now default to 9 train / 2 validation / 3 test.
- Split membership is persisted in immutable dataset manifests and reused by evaluation.
- Training is blocked when split settings changed but the dataset has not yet been rebuilt and revalidated.

## 3.8.15

- Fix PaddleX COCODetDataset compatibility: COCO `file_name` values are now relative to the dataset `images/` directory instead of incorrectly including an `images/` prefix.
- Mirror PaddleX's exact `dataset_dir/images/file_name` resolution in IsalaOCR validation so incompatible datasets are rejected before training.
- Add an explicit PaddleX COCO preflight to validation and training with actionable path diagnostics.
- Disable PaddleX dataset re-splitting explicitly during validation to preserve IsalaOCR's deterministic project split.
- Print PaddleX `check_dataset_result.json` on validation failure when available.
- Keep heavy training image revision 3.8.4 unchanged; the mounted localization runtime script updates without rebuilding training images.

## 3.8.14

- Fix localization COCO dataset build failure caused by recognition-model initialization writing to `/models/projects` inside the read-only dataset-builder container.
- Separate localization-only workspace resolution from recognition-aware workspace initialization.
- Apply the read-only localization workspace path to dataset validation and localization evaluation/reporting commands as well.
- Add regression coverage proving localization dataset build never calls project active-recognition directory creation.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.8.13

- Simplify Detection Review to four primary actions: Include, Not relevant, Incorrect and Adjust frame.
- Queue review decisions per ROI with a small concurrent background worker so review navigation does not wait for server writes.
- Default remaining open ROI candidates to Include when an image is marked complete, with an opt-out toggle.
- Add persistent `Afbeelding klaar` source review state and invalidate it whenever ROI ground truth changes.
- Remove the duplicate Detection Review Status workflow step and keep source status inside Detection Review.
- Make `Afbeelding klaar` a hard localization-dataset eligibility gate: incomplete source images are excluded entirely.
- Add an exact pre-build dataset preview with included/excluded image counts, positive/negative/adjusted/incorrect ROI counts, split counts and per-source inclusion rows.
- Keep heavy training image revision 3.8.4 unchanged.

## 3.8.11

- Detection Review Studio: visible busy indicator and disabled mutation controls while review requests are processing.
- Detection Review Studio: zoomable/pannable source viewer with Fit, +/−, 1:1, mouse-wheel zoom, Space-drag pan and fullscreen.
- Selection/geometry coordinates remain mapped to original source pixels at every zoom level.

## 3.8.10

- Redesign Detection Review selection around direct canvas interactions instead of a separate selection-window mode.
- Separate crop selection from geometry editing so normal clicks cannot accidentally move a candidate.
- Add live marquee preview with replace/add/subtract semantics and overlap-based selection.
- Add explicit per-candidate selection indicators, Select all visible, Ctrl+A and hover linking between canvas boxes and candidate cards.
- Add a floating batch-action toolbar for multi-selection while retaining the inspector for single-crop geometry work.
- Keep existing review APIs and training semantics unchanged.

## 3.8.9

- Split Step 1 preparation into files/source, download, download check, install/build and runtime/install check phases.
- Add per-component full-process actions plus bulk download/install/check/full preparation controls.
- Parallelize independent downloads while keeping heavyweight image builds sequential by default.
- Track validation markers against exact Docker image IDs and expose stale/unvalidated states separately.
- Add offline artifact checks for inference/localization models.
- Pin training-image setuptools below 81 for PaddleDetection `pkg_resources` compatibility.

## 3.8.8

- Replace user-facing action-number navigation with sequential workflow steps 1–21.
- Make Step 1 the single Preparation page with named component tasks.
- Hide internal action IDs from job queue, buttons, worker logs and preflight guidance.
- Keep internal action IDs backwards compatible for existing scripts and queued jobs.
- Remove artificial step numbers from system/maintenance pages.

## 3.8.7

- Replace fake 45% long-running job progress with indeterminate progress unless a real metric (such as training epochs) is available.
- Derive the live progress label from actual Docker/PowerShell output, including BuildKit step and layer-download information.
- Keep worker, STDOUT and STDERR logs separate and expose them as dedicated activity-terminal tabs.
- Default the activity terminal to live STDOUT with per-tab auto-follow and a `Naar live output` recovery button when manually scrolled away from the tail.
- Flag newly growing STDERR output in the terminal tab without mixing it into normal live output.

## 3.8.6

- Fix GPU PaddleDetection image build failure caused by PaddleX importing GPU PaddlePaddle during BuildKit, where `libcuda.so.1` is unavailable.
- Skip only PaddleDetection's optional external-deps/rotated-op hook during image build while preserving normal PaddleX repository installation.
- Validate PaddlePaddle CUDA visibility and PaddleDetection import after action 17 starts the built image with `gpus: all`.
- Keep the heavyweight training image tag at 3.8.4 so the existing CPU and GPU-recognition images remain reusable.

## 3.8.5

- Centralize all model/download preparation on Step 1 with a per-component readiness table.
- Show checkmarks for present artifacts and direct Download / build buttons for missing components.
- Add host-side Docker image verification through `models/preparation_status.json` and action 19.
- Refresh preparation status after every successful component and at web-worker startup.
- Keep heavy training-image revision 3.8.4 cached; only the application/UI release advances to 3.8.5.

## 3.8.4

- Fix PaddleDetection plugin installation by dropping its deprecated `sklearn==0.0` shim through PaddleX dependency replacement while retaining `scikit-learn`.
- Split the monolithic preparation path into actions 14–18 for inference models, CPU detector, GPU OCR recognition, GPU detector and pretrained recognition weights.
- Add a dedicated `isalaocr-training-gpu-detection` image/service so PaddleDetection failures cannot block GPU OCR-recognition training.
- Keep action 1 as the backwards-compatible prepare-all orchestrator.
- Keep PaddlePaddle 3.2.2 pins unchanged to avoid reintroducing the v3.8.3 CPU PicoDet/oneDNN regression.

## 3.8.3

- Fix PicoDet-S CPU preparation/inference crashing in PaddlePaddle 3.3.x with the upstream PIR/oneDNN `ConvertPirAttribute2RuntimeAttribute` regression.
- Pin reusable CPU and CUDA 11.8 training images to PaddlePaddle 3.2.2, the stable pre-regression runtime.
- Bump the heavyweight training-image revision to 3.8.3 so stale 3.7.0 images containing PaddlePaddle 3.3.0 cannot be reused.
- Add an explicit localization-runtime guard that rejects PaddlePaddle 3.3.x on CPU with an actionable diagnostic before PicoDet inference starts.
- Record the actual PaddlePaddle version in the localization preparation manifest.

## 3.8.2

- Fixed action 1 inheriting the legacy/global activated recognition model while warming the shared official OCR cache. Model preparation now always ignores custom/active recognition directories and prepares the configured official detection/recognition models.
- Installed PaddleOCR's `doc-parser` optional dependency group in the runtime image so PP-StructureV3 table/cell recognition has the PaddleX OCR/document-parser dependencies it requires.
- Added actionable error context for shared OCR and PP-StructureV3 model preparation failures.
- Added regression tests for official-cache isolation and PP-StructureV3 runtime dependencies.

## 3.8.1

- Fix labeler startup after project-workspace introduction by copying `training/projects.py` into the lightweight web image.
- Add static dependency-closure regression coverage for the labeler Dockerfile.
- Avoid Windows PowerShell 5.1 mojibake in project-path prerequisite messages.
- Training image revision remains 3.7.0.

## 3.8.0

- Add isolated project workspaces and a persistent project selector.
- Discover use-case templates from `application/config/use_cases`.
- Isolate detection/review state, localization datasets/models/gate, mappings, recognition datasets/registry/active models and project output.
- Pin queued worker jobs to their originating project.
- Give new projects an isolated input subpath while preserving `/input` for the migrated first project.
- Restore explicit-only localization supervision: positive/negative decisions train; unreviewed candidates are ignored.
- Make rejection reasons optional analysis metadata.
- Build contextual patches from partially reviewed screenshots so unknown fields are not implicitly trained as background.
- Keep multiselect, selection-window, keyboard and batch review UX.

## 3.7.6

- Block localization dataset builds until Detection Review has no pending candidates.
- Add one-click global finalization for exception-based review.
- Fix worker jobs that could report success despite `IsalaOCR failed` output.

## 3.7.5

- Detection Review Studio ondersteunt nu meervoudige cropselectie.
- Shift-klik in de kandidatenlijst selecteert een aaneengesloten reeks; Ctrl/Cmd-klik voegt losse kandidaten toe of verwijdert ze.
- Nieuw **Selectievenster**: sleep een rechthoek over de bronafbeelding om alle ROI-kaders waarvan het middelpunt in het venster valt tegelijk te selecteren.
- Correct/relevant, detectiefout en alle Niet-relevant-redenen werken als batchactie op de volledige selectie.
- Geometrie aanpassen/resizen blijft bewust een single-ROI-actie om onbedoelde boxwijzigingen te voorkomen.
- Batch review gebruikt één API-request en behoudt eerder aangepaste geometrie.
- De v3.7.4 viewport-fix blijft behouden; multiselect scrollt de documentpagina niet.

## 3.7.4

- Fixes Detection Review Studio page jumping when selecting ROI candidates.
- Candidate selection now scrolls only inside the candidate queue and never uses document-level `scrollIntoView()`.
- Candidate queue is an isolated scroll container to prevent scroll chaining into the page.
- Added regression coverage for stable viewport selection behavior.

## 3.7.3

- Detection Review Studio uses an exception-based fast-review workflow for large candidate sets.
- Open candidates are visually treated as provisional Correct + Relevant; only exceptions require per-candidate interaction.
- Added one-click out-of-scope reason buttons and keyboard shortcuts 1–7; removed the mandatory relevance dropdown.
- Added **Bron afronden & volgende** to bulk-accept remaining open candidates and continue with the next source.
- Added fast-review regression coverage.

## 3.7.2

- Scheidt geometriekwaliteit van relevantie voor de actuele OCR-scope in Detection Review Studio.
- Technisch correcte maar niet-relevante kandidaten worden `ignore`-regio's in plaats van false positives.
- Mapping Studio ontvangt alleen relevante, beoordeelde Pipeline-A geometrie.
- Localization-dataset/evaluatie negeert out-of-scope regio's expliciet.
- Database schema v12 voegt scope- en training-role metadata toe.

# Changelog

## 3.7.1

- Herstelt START.cmd/webinterface-start door action 3 in de centrale preflight action catalog te registreren.
- Corrigeert gerecyclede legacy action-ID's na de 3.7.0 pipeline-hernummering.
- Voegt regressietests toe voor PowerShell action-catalog/preflight-consistentie.
- Training image revision blijft 3.7.0; geen onnodige rebuild voor deze host-side hotfix.



## 3.7.0

- Split field localization/crop geometry from value mapping/OCR with a hard detection gate.
- Added Detection Review Studio with editable boxes, explicit negatives and manually added missed fields.
- Added separate localization database entities and single-class COCO dataset builder.
- Added PaddleX/PaddleDetection field-detector preparation, training, prediction and evaluation flow.
- Added geometry metrics and explicit quality-gated localization model activation.
- Made reviewed Pipeline-A geometry authoritative for final mapped crops.
- Reorganized web/PowerShell actions into Field Detection (1–13) and Value Mapping & OCR (20–28).

## 3.6.4

- Added structured **Afkeuren & leren** feedback to Mappingstudio.
- Store explicit rejection reasons plus relation snapshots as durable negative training examples.
- Store confirmed relations as positive feedback examples.
- Added a feedback-aware relation-quality learner that suppresses exact rejected patterns and penalizes similar future proposals.
- Re-apply same-source rejection feedback after redetection using normalized text/value/context/geometry signatures.
- Rejecting a relation removes its mapping, invalidates any mapped ROI derived from it and prevents accidental reconfirmation until restored.
- Added rejection/restoration controls, rejected-status filtering, visual rejected state and live feedback statistics.
- Increased the training database schema to v10.
- Added regression coverage for the feedback lifecycle and learning behavior.


## 3.6.3

- Reviewed the generic/Paddle workflow for functional correctness, extraction effectiveness and Mappingstudio UX.
- Made Mappingstudio saves atomic and made clearing a mapping an explicit database removal.
- Retire stale mapped ROI/value samples when mappings or detection geometry change.
- Prevent one detected relation/value from silently feeding multiple functional fields.
- Remove orphan mappings after redetection and deterministically rebuild automatic suggestions.
- Use PP-Structure internal OCR as a per-cell fallback and assign OCR tokens to one best-fitting cell.
- Added mapping search, source/status/confidence filters, sticky spatial output preview, duplicate-field guard and quick previous/next navigation.
- Added regression coverage for mapping lifecycle, table-cell OCR fallback and reviewed UX controls.

## 3.6.2

- Added PaddleOCR PP-StructureV3 table/cell detection before semantic mapping.
- Added table-aware row/column relations with table relations preferred over overlapping OCR-distance proposals.
- Kept final ROI crops token-tight by resolving exact OCR boxes inside selected value cells.
- Added a Paddle table-structure view with row/column metadata.
- Added a live selected-data JSON output preview to Mappingstudio.
- Added PP-Structure model preparation and database schema v9 table metadata.


## 3.6.1

- Corrected generic ROI geometry and semantic row grouping.
- Added adaptive ROI refinement from exact OCR-token geometry.
- Prevented automatic mapping of reference-range values.
- Simplified Detectieweergave to mapping candidates by default.

## 3.6.0

- Replaced profile-first field extraction with a generic detection-and-mapping workflow.
- Added neutral full-page detection of OCR blocks, labels, values, units, headers and spatial relations without assigning a functional field key.
- Added a crop-first **Detectieweergave** for inspecting every detected block and proposed label/value relationship.
- Added **Mappingstudio** for confirming automatic suggestions, mapping each detected relationship, or manually pairing label and value blocks.
- Added an editable **Veldschema** with field groups, datatypes, units, aliases, validation ranges and active/inactive state.
- Added reusable **Mappingprofielen** that transfer semantic mapping rules to comparable sources as reviewable suggestions.
- Split mapping application from value recognition: action 20 creates ROI crops only; action 21 reads only ROI-approved crops.
- Added structured output containing raw OCR, parsed value, parsed unit, parse status, range validation, mapping confidence and ROI coordinates.
- Migrated the training database to schema v8 with separate sources, blocks, relations, field definitions, mappings and mapping profiles.
- Kept the existing Philips CMR configuration as editable starter schema and legacy compatibility data rather than detector logic.
- Expanded the process navigation to twenty distinct tabs from model preparation through model activation.
- Kept the labeler container lightweight by loading OpenCV, NumPy and OCR runtime dependencies only inside worker-side mapping operations.


## 3.5.19

- Show the actual ROI crop beside every detected block in the detection view.
- Distinguish dynamic detections from fixed fallbacks with badges and dashed overlay styling.
- Explain per fallback why the dynamic locator rejected the header match and show the expected and observed header.
- Link trainable fallback matches directly to the exact row in **Rijheaders trainen**.
- Add source, sample and extraction-method filters to focused row-header correction.
- Document the recovery flow: correct mapping, train normalization, then rerun DICOM detection.
- Mark fallbacks without a detected header as non-trainable instead of implying normalization can repair them.

## 3.5.18

- Extract the Philips **Study info** line during DICOM analysis.
- Expose heart rate, BSA, BSA method, height, weight and gender as separate named output fields.
- Preserve the complete raw OCR line and per-field raw OCR fragments alongside parsed values.
- Write a dedicated `training/workspace/extracted_output/<source_id>.json` file for each analysed source.
- Show the structured study fields, raw text and confidence in the detection view.
- Add the same `study_info` object to normal `result.json` and `result.txt` output.
- Keep patient names, patient IDs, accession numbers and DICOM UIDs excluded from generated output.


## 3.5.17

- Show the unmodified row-header OCR token text explicitly in **Rijheaders trainen**.
- Show the normalized comparison key separately so OCR, normalization and semantic field mapping can be inspected independently.
- Rename the displayed locator confidence to **Locator-matchscore** to avoid presenting it as OCR confidence.
- Add regression coverage that verifies the raw OCR text remains visible alongside the normalized form.


## 3.5.16

- Fixed ROI overlays being positioned relative to a vertically stretched grid cell instead of the rendered source image.
- Added a dedicated image-sized overlay stage shared by detection view and ROI review.
- Kept overlay coordinates stable inside scrollable and sticky viewers.
- Added explicit source image dimensions to prevent layout shifts while the PNG is loading.
- Added regression tests for the overlay coordinate-system structure.


## 3.5.15

- Added a dedicated **Rijheaders trainen** process tab between detection and ROI review.
- Added independent review state, target-field selection, corrected header text and notes for detected row headers.
- Added a deterministic learned-alias normalizer that maps noisy locator OCR to configured semantic fields.
- Added separate buttons to save reviews, train the normalizer, and train plus queue a fresh DICOM detection run.
- Stored row-header crops and coordinates separately from value ROI crops.
- Automatically reset a header review when the observed locator text changes.
- Excluded ambiguous aliases that map to multiple fields inside the same panel.
- Updated the workflow from thirteen to fourteen process steps.


## 3.5.14

- Redesigned **Modellen vergelijken** as a strict side-by-side view: new/custom model on the left and old/baseline model on the right.
- Added separate evaluation buttons plus an ordered **Alles uitvoeren** queue for custom evaluation, baseline evaluation and comparison.
- Added per-field and per-sample comparison results with expected label, prediction, confidence, improvement/regression status and filters.
- A completed comparison now exits successfully even when the custom model is not better; model quality is represented by the verdict instead of the worker exit status.

## 3.5.13

- Strictly separated spatial ROI assessment from OCR value assessment in routes, filters, templates and status counts.
- Limited value review, smart approval and duplicate reuse to ROI-approved samples.
- Removed ROI/extraction actions and locator metadata from all value-review screens.
- Removed OCR text, OCR confidence and value status from all ROI-review screens.
- Invalidated value decisions when their ROI becomes pending or incorrect and preserved the old decision in review history.
- Restricted training datasets to accepted values with a definitively correct ROI.
- Migrated legacy `roi_error` value statuses into the dedicated ROI review state.
- Added a persistent deferred ROI state so “Later” no longer conflicts with the default-OK state for new ROI samples.

## 3.5.12

- Fixed queued actions opening an interactive PowerShell prompt instead of executing the requested script.
- Replaced use of the automatic `$args` variable with an explicit non-interactive command line.
- Stop obsolete worker process trees during an application update.
- Recover interrupted running jobs as retryable failed jobs with a clear reason.

## 3.5.11

- Split the web workflow into thirteen process-specific navigation tabs.
- Added process-specific requirements, actions, status and result panels.
- Made queued and running job output immediately visible.
- Added worker lifecycle logging and robust Windows log decoding.
- Added versioned static asset URLs to prevent stale browser JavaScript.

## 3.5.10
- ROI-review gebruikt nu een standaard-OK/opt-out-beoordelingsflow.
- Pending ROI's worden bij openen als correct voorgeselecteerd en bij opslaan bevestigd.
- Visuele ROI-status wordt direct bijgewerkt bij wijzigingen.

## 3.5.9 - 2026-08-06

- Added dedicated ROI assessment workflow and navigation tab.
- Added persistent ROI review state per sample.
- Improved overlay-to-value selection in the DICOM viewer.

## 3.5.8 - 2026-08-06

- Fixed false failed task states caused by unreliable child-process exit-code handling in Windows PowerShell 5.1.
- Worker actions now run through a temporary `cmd.exe` wrapper that propagates the real exit code.

## 3.5.7
- Activatie hernoemd naar Models.
- Officiële small- en medium-modellen zijn selecteerbaar.
- Worker registreert succesvolle processen correct onder Windows PowerShell 5.1.

## 3.5.6 - 2026-08-06

- Added safe self-cleaning of interrupted temporary artifacts before crop collection.
- Automatically infer the actual PaddleOCR model family from activated model metadata.
- Changed crop collection model selection from a forced small model to automatic selection.
- Preserved all source DICOMs, reviews, datasets, runs, registered models and active-model content.

## 3.5.6 - 2026-08-06

- Fixed PowerShell 5.1 UTF-8 BOM JSON files causing the web container to treat a healthy worker as unreachable.
- Worker heartbeat and job status JSON are now written as UTF-8 without BOM.
- Web UI JSON reader also accepts legacy BOM-prefixed status files.
- Existing queued and running tasks remain visible and are recovered without re-queuing.

## 3.5.4 - 2026-08-06

- Replaced PID-only worker locking with heartbeat, process-name and command-line validation.
- Automatically removes stale worker state and verifies worker startup before opening the web interface.
- Added startup stdout/stderr logs and removed duplicate worker console messages.

# Changelog

## 3.5.3 - 2026-08-06

- Added queue-management page and visible worker status output.


## 3.5.2 - 2026-08-06

- Fixed the Windows PowerShell 5.1 web worker crash when queued job JSON lacks runtime-only properties such as `started_at`.
- Worker now adds or replaces job state properties with `Add-Member -Force` instead of assigning missing PSCustomObject members directly.
- Existing queued jobs from v3.5.0/v3.5.1 are processed without recreation.

## 3.5.2 - 2026-08-06

- Added a persistent bottom activity dock with live terminal output and progress.
- Job submission now gives immediate feedback without waiting for a page reload.
- Pending jobs are visible before the PowerShell worker polls them.
- Added worker heartbeat, current-job reporting and live status updates.
- Automatically restarts an idle old worker and recreates an outdated web container after updates.
- Combined stdout and stderr in the browser log viewer.
- Registration and activation pages refresh after successful completion.
- Added explicit four-stage activation output.

## 3.5.0

- Unified local web control panel for DICOM inspection, overlay review, smart review, training and activation.
- Added local source renders and background host job worker.

# Changelog

## 3.5.3 - 2026-08-06

- Added queue-management page and visible worker status output.

## 3.4.8 - 2026-08-06

- Add a compact four-phase training console with a total per-epoch progress bar.
- Show validation accuracy, best epoch, loss, ETA and GPU memory in one concise line per epoch.
- Preserve the complete unfiltered PaddleX/PaddleOCR stream in `training-console.log`.
- Write live and final machine-readable state to `training-progress.json`.
- Keep warnings, errors and tracebacks visible even in compact mode.
- Add optional `-DetailedOutput` for full console streaming alongside the progress view.
- Reuse training image revision 3.3.12; no Docker image rebuild is required.

## 3.4.7 - 2026-08-06

- Add a runtime NumPy pickle compatibility layer for official PaddleOCR weights published from NumPy 2.
- Alias `numpy._core.multiarray` to the equivalent NumPy 1.x implementation only when the native NumPy 2 package path is absent.
- Propagate the compatibility startup module into the nested PaddleX/PaddleOCR training subprocess.
- Add fail-fast NumPy pickle verification before training, evaluation and export.
- Reuse training image revision 3.3.12; no Docker image rebuild is required.

## 3.4.6 - 2026-08-06

- Make option 1 always run the versioned CPU and GPU Compose builds; BuildKit still reuses existing layers.
- Verify `isalaocr-training-cpu:3.3.12` and `isalaocr-training-gpu:3.3.12` directly with `docker image inspect` after each build.
- Re-check the exact CPU image immediately before the offline `training-setup` container starts, preventing the opaque Docker `No such image` failure.

## 3.4.5 - 2026-08-06

- Pin Shapely 2.1.2 in reusable training images to satisfy the pinned PaddleOCR source API.
- Add runtime verification for the top-level `shapely.intersection` function before training.
- Bump training image revision to 3.3.12 while preserving the existing heavyweight dependency layer for BuildKit reuse.
- Make PowerShell menu action-definition and argument dispatch null-safe.
- Automatically remove Mark-of-the-Web from project scripts and show the installed version in the menu.

## 3.4.4

- Removed the separate GPU Compose runtime probe from the Windows PowerShell 5.1 preflight.
- CUDA validation remains fail-fast inside the actual trainer-gpu container before training.
- Prevented the recurring null-valued expression crash when selecting option 10.

## 3.4.3 - 2026-08-06

- Fixed the remaining Windows PowerShell 5.1 null-expression failure in option 10.
- Added a dedicated PaddlePaddle GPU runtime-check command.
- Short-circuited GPU probing when earlier training prerequisites fail.
- Added durable preflight crash diagnostics.

# Changelog

## 3.5.3 - 2026-08-06

- Added queue-management page and visible worker status output.

## 3.4.2 - 2026-08-06

- Recovered valid existing datasets when `latest.txt` is stale, malformed, BOM-prefixed, or missing.
- Made `characters.txt` optional for option 8; labels are inspected directly and `dict.txt` is synchronized during validation.
- Made GPU, Docker, Compose, and workspace-doctor preflights null-safe under Windows PowerShell 5.1.
- Converted unexpected preflight implementation exceptions into explicit failed check rows instead of aborting the menu.

## 3.4.1 - 2026-08-06

- Moved pretrained-weight network access to the proven model-prep container.
- Made training-setup explicitly offline and deterministic.
- Added conditional preflight checks for cached weight size and official model-host reachability.
- Added cleanup and clearer diagnostics for failed partial downloads.

## 3.4.0 - 2026-08-06

- Centrale `START.cmd` als enige bestand in de projecthoofdmap.
- Automatische preflight vóór alle 16 menuacties.
- Check-only mode en algemene all-actions readiness-check.
- Host- en containercontrole van schrijfpermissies.
- Beperkte bind-mountreparatie met verificatie achteraf.
- Projectinhoud gegroepeerd onder application/automation/documentation/infrastructure/project.
- Build-only en runtime-services voor herbruikbare CPU/GPU-trainingimages gescheiden.

## 3.3.12 - 2026-08-06

- Do not fail pretrained-weight preparation when only the optional JSON manifest is blocked by legacy bind-mount permissions.
- Reuse training image revision 3.3.11; no CUDA/Paddle dependency rebuild is needed.

# Changelog

## 3.5.3 - 2026-08-06

- Added queue-management page and visible worker status output.

## 3.3.11

- Added a pinned, cached PaddleOCR training checkout because the vendor image does not include one.
- Fixed reusable training-image preparation failing with `PaddleOCR training repository was not found in the vendor base image`.
- Preserved the heavy CUDA/PaddlePaddle/PaddleX build cache.

## 3.3.11 - 2026-08-06

- Fixed non-root training failing while probing the vendor repository at `/root/PaddleOCR`.
- Published the existing PaddleOCR checkout through `/opt/isala-paddleocr` and granted only traversal on `/root`.
- Added a build-time read test under the configured application UID/GID.
- Made repository discovery skip inaccessible candidates instead of raising an unhandled `PermissionError`.
- Bumped the reusable CPU/GPU training image revision to 3.3.11 while retaining the heavyweight dependency layers ahead of the new access layer for BuildKit reuse.
- Preserved all datasets, 224 reviews, crops, model caches and previous training runs.

## 3.3.9 - 2026-08-05

- Fixed `PP-OCRv6_medium_rec` training failing because the PaddleX source distribution did not initialize its PaddleOCR repository API registry.
- Added deterministic local PaddleOCR repository discovery and explicit repository-API registration before PaddleX CLI execution.
- Added validation of the registered model and runner root before training, evaluation or export proceeds.
- Mounted the host `training_runtime` read-only into reusable training containers so this runtime-only repair does not rebuild or redownload the v3.3.7 CPU/GPU images.
- Preserved all datasets, 224 reviews, crops, model caches and previous training runs.

## 3.3.8 - 2026-08-04

- Replaced unsupported `docker compose run --no-build` calls with supported `--pull never` runs after a local image preflight.
- Decoupled the heavyweight training-image revision from the application release through `TRAINING_IMAGE_VERSION`.
- Reuses the fully built v3.3.7 CPU/GPU images for this host-script-only hotfix.
- Menu option 1 now skips CPU/GPU builds when the required local images already exist.
- Preserves all datasets, labels, reviews, model caches and training runs.

## 3.3.7 - 2026-08-04

- Separated heavyweight PaddlePaddle/PaddleX installation from build verification so verification changes no longer invalidate the dependency layer.
- Prebuilds both CPU and NVIDIA GPU training images from menu option 1.
- Shares one versioned CPU image between training setup and CPU training.
- Treats stale PaddleX 3.3.11 distribution metadata from the legacy base image as diagnostic while keeping the checksum-pinned 3.7.2 source overlay authoritative.
- Preserves offline runtime behavior and existing training/model data.

## 3.3.6 - 2026-08-04

- Stop importing CUDA PaddlePaddle during Docker image build, where host driver library `libcuda.so.1` is intentionally unavailable.
- Verify PaddlePaddle/PaddleX distribution versions, package locations and `libpaddle.so` without loading the CUDA runtime.
- Defer PaddlePaddle import to container runtime after `gpus: all` can inject the NVIDIA driver libraries.
- Add a targeted GPU runtime preflight for CUDA compilation and visible-device count.
- Return actionable diagnostics when the NVIDIA runtime or GPU is unavailable.
- Add regression tests for the Docker build/runtime boundary.

## 3.3.5 - 2026-08-04

- Prepare the official `PP-OCRv6_medium_rec` inference model for offline baseline evaluation.
- Resolve recognition-only models from the local PaddleX `official_models` cache.
- Ensure named baseline evaluation ignores activated custom model directories.
- Block implicit model downloads when `allow_downloads` is false.
- Add a host-side baseline cache preflight before launching the offline evaluator.
- Add preparation and regression tests for the baseline inference cache.

## 3.3.4 - 2026-08-04

- Prevented PaddleX dataset validation from downloading `PingFang-SC-Regular.ttf` at runtime.
- Baked Matplotlib's bundled DejaVu Sans into the training image and configured `PADDLE_PDX_LOCAL_FONT_FILE_PATH`.
- Added a build-time font readability and IsalaOCR character smoke test.
- Applied the local font setting to training setup, CPU training and GPU training services.
- Preserved the offline `network_mode: none` security boundary.

## 3.3.3 - 2026-08-04

- Fixed `PermissionError` while writing `charset_report.json` to a validation run directory created by an older container identity.
- Added host-side creation and write probing for validation, training, evaluation and comparison output directories before Docker starts.
- Menu option 8 now removes only its disposable stale `check-<dataset>` directory and recreates it from Windows; reviewed labels, datasets and model runs are untouched.
- Added a container-side output-directory write probe so remaining mount problems fail with an actionable message before PaddleX starts.
- Preserved the synchronized official PP-OCRv6 dictionary and all existing training data.

## 3.3.2 - 2026-08-04

- Fixed `PermissionError` while synchronizing `dataset/dict.txt` on existing reviewed datasets.
- Aligned `training-setup`, `trainer-cpu` and `trainer-gpu` with the same numeric UID/GID (10001:10001) used by the collector, dataset builder and labeler.
- Added configurable `ISALA_APP_UID` and `ISALA_APP_GID` Compose values without weakening host permissions or running training as root.
- Added an early writable-directory probe with an actionable UID/GID diagnostic instead of a raw `pathlib` traceback.
- Preserved all DICOMs, crops, 224 reviews, exact labels, datasets and model files.

## 3.3.1 - 2026-08-04

- Baked the official PP-OCRv6 recognition dictionary into the training image from a pinned PaddleOCR commit.
- Added Git blob verification so a mutable or incomplete dictionary cannot be accepted silently.
- Made the training runner prefer the deterministic bundled dictionary while retaining legacy full-checkout discovery for compatibility.
- Fixed menu option 8 failing because the PaddleX source distribution did not include `ppocr/utils/dict/ppocrv6_dict.txt`.

## 3.3.0 - 2026-08-04

- Synchronize PaddleX-required `dict.txt` from the official PP-OCRv6 dictionary.
- Preserve the pretrained recognition vocabulary instead of shrinking it to locally observed characters.
- Validate exact label character coverage, including verbatim spaces and `²`.
- Auto-repair existing 3.2.x datasets before validation, training and PaddleX evaluation.

## 3.2.9 - 2026-08-04

- Fixed PaddleX command construction so every configuration override is preceded by its own `-o` option.
- Applied the fix consistently to dataset validation, training, evaluation and export.
- Added regression coverage for multi-override PaddleX commands.

## 3.2.8 - 2026-08-04

## 3.2.8

- Replaced the missing PP-OCRv6 training configuration path with a checksum-pinned PaddleX 3.7.2 source overlay.
- Pinned PaddlePaddle 3.3.0 separately for CPU and CUDA 11.8 GPU training images.
- Added build-time verification of `PP-OCRv6_medium_rec`, PaddleX `main.py`, installed PaddleX and PaddlePaddle.
- Retained deterministic Path-aware configuration discovery and added regression coverage for all training build arguments.

- Fixed validation and training failing because the previous base image contained PaddleX 3.3.11, which predates PP-OCRv6 and lacks `PP-OCRv6_medium_rec` configuration.
- The training image now overlays the pinned PaddleX 3.7.1 source distribution and verifies its published SHA-256 digest.
- The Docker build fails immediately when the pinned source lacks `main.py` or the PP-OCRv6 medium recognition configuration.
- Menu option 1 now verifies the matching PaddleX entry point and configuration before reporting success.
- Existing DICOMs, reviews, datasets, model files and SQLite data are not included or replaced.

## 3.2.7 - 2026-08-04

- Consolidated the complete v3.2.0 codebase and hotfixes v3.2.1 through v3.2.6 into one source distribution.
- Fixed PaddleX dataset validation crashing because `len()` was called directly on `pathlib.Path` objects during training-runtime discovery.
- Added deterministic Path-aware discovery ordering for both PaddleX configuration and `main.py` candidates.
- Synchronized project, package and labeler-image version metadata.
- Added regression coverage for PaddleX training-runtime discovery.
- The archive contains no DICOMs, labels, crops, datasets, models or SQLite databases, so it can be overlaid on an existing installation without replacing local training data.

## 3.2.5 - 2026-08-04

- Fixed PaddleX startup on offline/read-only containers by making the local model cache writable at runtime.
- Added a cache write probe before PaddleX import, producing one actionable error instead of repeated initialization failures.
- Added batch warm-up so locator and recognition engines initialize once before processing DICOMs.
- Disabled PaddleX model-source connectivity checks for offline runtime services.

## 3.2.2 - 2026-08-04

- Fixed upgrades from schema v2 failing on `idx_samples_method` before the new `extraction_method` column existed.
- Database migrations now add columns before creating indexes that depend on them.
- Existing labels, review statuses and notes are preserved during migration.
- A SQLite-consistent `samples.before-schema-v4.sqlite3` backup is created once before changing an older database.
- Added recovery for the partially created schema left by the failed v3.2.0 collection attempt.

## 3.2.1 - 2026-08-04

- Fixed a Windows PowerShell 5.1 preflight bug that could reject a complete successful `docker version` response as unavailable.
- Refreshes the native process before reading `ExitCode` and accepts a complete Docker Server/Engine/Linux response as a safe fallback.
- Docker Desktop is now started automatically when the CLI exists but the engine is not available.
- Waits up to 180 seconds for the Linux engine and then continues the selected menu action automatically.
- Searches standard Program Files, LocalAppData, registry App Paths and PATH locations for `Docker Desktop.exe`.

## 3.2.0 - 2026-08-04

- Replaced fixed row coordinates in the training collector with dynamic label-row localization.
- Added table-header, panel-divider and value-column detection; row order may now vary between screenshots.
- Added explicit `screen_labels` and `panel` metadata to the Philips CMR profile.
- Kept legacy fixed ROIs only as visible `fixed_fallback` samples.
- Added locator overlays and per-source JSON diagnostics.
- Added crop hashes, locator metadata and review history to the SQLite schema.
- Previously approved samples remain approved only while the crop pixels are unchanged; changed crops return to `pending` once.
- Added explicit buttons for value present, corrected value, visible placeholder, truly empty ROI, extraction error and unreadable content.
- Prevented the current sample from reappearing after approval by re-querying the queue with an explicit sample exclusion.
- Added extraction-method filters and locator-confidence display to the local interface.
- Added 53 passing regression tests and a 14-screen Tesseract locator smoke test.

## 3.1.0 - 2026-08-04

- Added a default review queue for pending, non-empty OCR results below 80% confidence.
- Added confidence range filters and OCR-content filters to the local label interface.
- Added separate queues for empty crops, missing-value markers and high-confidence spot checks.
- Added the `no_value` review status; these samples are never included in recognition training datasets.
- Preserved all review filters while moving between samples.
- Added percentage-based confidence display and low-confidence highlighting.

# Changelog

## 3.5.3 - 2026-08-06

- Added queue-management page and visible worker status output.

## 3.0.6 - 2026-08-04

- Fixed Windows PowerShell 5.1 treating Docker Compose's harmless `No stopped containers` message as a fatal error.
- Replaced unconditional `docker compose rm` with explicit, idempotent container discovery and removal.
- Container discovery now includes stopped labeler containers.
- Docker stderr warnings no longer abort labeler compose validation or startup.
- Diagnostics stay best-effort after loading shared scripts.
- Stopping the label interface is now safe when no container exists.

## 3.0.4 - 2026-08-04

- Labelinterface volledig geïntegreerd in `TRAINING_MENU.cmd`: starten/openen, stoppen en diagnose.
- Bestaande gezonde labelcontainer wordt hergebruikt in plaats van telkens opnieuw gebouwd.
- Gekozen hostpoort wordt opgeslagen en door de diagnosefunctie automatisch gebruikt.
- Automatische poortselectie 8088-8098 en health-check vóór openen van de browser.
- Fouten keren gecontroleerd terug naar het hoofdmenu.

## 3.0.1

- Fixed `collect-training-data.ps1`: renamed the PowerShell parameter from `$Input` to `$InputPath` to avoid collision with PowerShell's automatic `$input` variable.
- Added explicit validation and robust argument-array invocation for Docker.

## 3.0.0 - 2026-08-03

- Volledige lokale PP-OCRv6 recognition fine-tuningpipeline toegevoegd.
- ROI-cropcollector met ruwe recognition-only baseline en privacyveilige bron-ID's.
- Lokale browserinterface en SQLite-database voor exacte transcripties.
- Geen label- of evaluatienormalisatie; tab/newline/NUL zijn uitsluitend om technische redenen verboden.
- Deterministische train/validatie/test-splitsing per bron-DICOM.
- Milde, labelbehoudende augmentatie uitsluitend op trainingsdata.
- PP-OCRv6 medium CPU- en NVIDIA-GPU-training via officiële PaddleX-runtime.
- Dataset- en dictionarycontrole vóór training.
- Baseline/custom evaluatie met exact-match accuracy, CER, per-veldmetrics en confusion pairs.
- Modelregister, kwaliteitsdrempel en expliciete activatie naar `models/active-recognition`.
- Windows `.cmd`-starters om lokale scripts uit te voeren zonder permanente wijziging van Execution Policy.
- Gevoelige trainingspaden uit Git- en Docker-buildcontext verwijderd.
- Regressietests toegevoegd voor exacte labels, bronlekkage, augmentatie, collector, metrics en modelactivatie.

## 2.0.1 - 2026-08-03

- PaddleOCR-crash op tweedimensionale grijsbeelden opgelost door centrale conversie naar aaneengesloten drie-kanaals `uint8`.
- Regressietests voor grijs-, éénkanaals-, alfakanaals- en ongeldige OCR-invoer.

## 2.0.0 - 2026-08-03

- Volledige herbouw op PaddleOCR 3.x en PP-OCRv6.
- Batched ROI-inference, layoutankers, validatie en privacyveilige bronhashes.
- Offline Docker-runtime en gestructureerde output.

## 3.0.7 - 2026-08-04

- Rebuilt the exact-label web service on a dedicated lightweight Docker image.
- The labeler no longer installs or rebuilds PaddleOCR, PaddlePaddle, OpenCV,
  DICOM codecs, or Tesseract.
- Added a minimal labeler-only entry point independent of the main OCR CLI.
- This reduces build size/time and avoids Docker Desktop image-export failures
  caused by unpacking the full OCR runtime merely to open the labeling UI.

## 3.2.3 - Reusable Docker dependency cache

- Moved heavyweight Python dependencies into `requirements-runtime.txt`.
- The dependency layer is now built before application source is copied, so
  source/config updates no longer reinstall PaddleOCR and related packages.
- Added persistent BuildKit caches for pip and apt downloads.
- The collector may still run `docker compose ... --build`; unchanged layers
  should now be reported as `CACHED` and no packages should be downloaded.
- The first build after installing this update creates the new cache once.

## 3.2.6 - 2026-08-04

- Fixed menu option 1 so it prepares the PP-OCRv6 small inference models required by crop collection before preparing the medium training weight.
- Removed the misleading `No module named 'paddleocr'` inference-cache note from the training-only image.
- Added host-side verification for the inference manifest, model-cache files, and medium pretrained weight.
