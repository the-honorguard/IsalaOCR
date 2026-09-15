# Vervolgrefactor — uitvoeringsplan (fase 2)

Status: bezig. Vervolg op `documentation/architecture/db-webui-split-plan.md`
(afgerond) en `documentation/CODE_REVIEW_v3.16.0.md` (oorspronkelijke
bevindingen). Dekt alle nog openstaande punten uit dat rapport die niet al in
fase 1 zijn afgehandeld. Elke stap is een eigen commit op
`claude/code-review-calls-jc8xyn` (PR #38), alleen gepusht nadat de volledige
testsuite groen is (op de 6 vooraf-bestaande, onafhankelijke falende tests
na — zie validatieprotocol onderaan).

## Volgorde (naar risico/omvang, kleinste/veiligste eerst binnen elk blok)

1. **Raw-SQL-plekken → `TrainingDatabase`-methodes.** 12+ plekken buiten
   `db.py` die rechtstreeks SQL uitvoeren tegen dezelfde tabellen, plus
   `projects.py`'s eigen `sqlite3.connect()` met silent
   `except sqlite3.OperationalError: pass`.
2. **Gedeelde geometrie/IoU-module.** 4 onafhankelijke implementaties met
   afwijkende edge-case-semantiek (clamp op 1 vs. epsilon 1e-9 vs. geen
   guard) samenvoegen.
3. **`FieldSpec.whitelist` no-op in PaddleEngine** — eerst onderzoeken
   (raakt productie-OCR-nauwkeurigheid), dan pas fixen indien veilig.
4. **Twee `_similarity`-functies** (`mapping.py`/`dynamic_locator.py`) —
   beoordelen, samenvoegen of expliciet documenteren.
5. **CLI-duplicatie**: locator-constructie (4×), detectiegate-sync (2×),
   eigen argv-scanner in `table_first_cli.py`, ontbrekend `--log-level`/
   try-except in `recognition_gt_cli.py`, inconsistente exit-codes.
6. **PowerShell-scriptinconsistenties** (`activate-*-model.ps1`,
   `training-status.ps1`).
7. **Gedeelde JSON-foutrespons-helper** voor Flask-routes.
8. **Overige lage-risico opruimpunten**: onbereikbare `gt_studio.js`/
   `gt_studio.html`, dode `DocumentResult.errors`, `410 Gone`-endpoint,
   `table_structure.py`'s tijdelijke lab-methoden.
9. **Losse correctheids-signalen**: `assert` op `None` in `consistency.py`,
   fire-and-forget `ThreadPoolExecutor` zonder `.result()`-check,
   `retry_job` dupliceert queue-schrijflogica i.p.v. `enqueue_job`.
10. **Frontend: 4 review-studio-implementaties unificeren.** Groot, apart
    traject (JS, geen python-testdekking) — als laatste, in kleine stappen,
    expliciet stoppen/documenteren als een stap niet veilig te verifiëren is.

Elk item hierboven wordt hieronder met `[ ]`/`[x]` bijgehouden zodra de
inventarisatie/uitvoering start.

## Inventaris item 1 (raw-SQL-plekken, huidige regelnummers)

- [x] `projects.py:401-451` (`_rewrite_duplicated_project_paths`) — het
      risicovolste geval (eigen `sqlite3.connect()`, silent
      `except sqlite3.OperationalError: pass`). Opgelost via nieuwe
      `TrainingDatabase.rewrite_localization_paths()` in `db_localization.py`
      (`LocalizationMixin`). De twee `sqlite3.connect()`-aanroepen op
      `projects.py:401-402` (bestandsniveau-backup via SQLite's eigen
      backup-API bij het dupliceren van een project) blijven bewust
      ongewijzigd: die werken op een ander project se databasebestand, niet
      op de actieve `TrainingDatabase`-instantie, en horen niet bij "raw SQL
      tegen dezelfde tabellen".
- [x] `table_quality.py:74-110` (`table_first_quality`, 4 queries in 1
      `db.connect()`-blok) — verplaatst naar nieuwe
      `TrainingDatabase.table_first_quality_rows()`
      (`db_detection_review.py`, `DetectionReviewMixin`), die de 4 queries
      ongewijzigd uitvoert en als lijsten van `dict`s teruggeeft (in plaats
      van `sqlite3.Row`, maar met dezelfde `row["kolom"]`-toegang, dus geen
      wijziging nodig in de consumerende aggregatielogica in
      `table_quality.py`).
- [x] `webui.py:918,939,969,1042,1068,1089` (6 plekken, allemaal op
      `samples`) — verplaatst naar `SamplesMixin` (`db_samples.py`):
      `source_summary_rows()`, `samples_for_source(source_id)`,
      `roi_review_status_counts()`, `mapped_value_review_status_counts()`,
      `mapped_value_review_source_rows()`,
      `mapped_value_review_source_samples(source_id)`. De webui.py-closures
      (`source_rows`, `source_samples`, `roi_review_counts`,
      `value_review_counts`, `value_source_rows`, `value_source_samples`)
      zijn nu dunne aanroepen; `source_rows()` behield alleen de
      `render_exists`-berekening (die `workspace_root()` nodig heeft).
- [x] `recognition_ground_truth_web.py:29,53,74,101,161,207` (6 plekken,
      allemaal op `samples` gefilterd op `extraction_method`) — verplaatst
      naar `SamplesMixin`: `accepted_exact_labels(extraction_method)`,
      `has_accepted_exact_label(extraction_method)`,
      `accepted_exact_label_rows(extraction_method)`,
      `samples_source_counts(extraction_method, status, sort)`,
      `samples_for_source_and_method(source_id, extraction_method)`,
      `samples_by_method(extraction_method, status)`. `sort`/`status`
      blijven server-side gevalideerde parameters (geen directe
      request-string-interpolatie in de SQL).
- [x] `recognition_ground_truth.py:304,438,444` — verplaatst naar
      `SamplesMixin`: `samples_status_counts(extraction_method)` (voor
      `recognition_gt_counts`) en `mark_stale_samples(extraction_method,
      keep_sample_ids, stale_extraction_method)` (voor de read+update-combo
      in `materialize_recognition_ground_truth`, die nu net als voorheen in
      één transactie gebeurt).
- [x] `routes_roi_review.py:35` — verplaatst naar
      `SamplesMixin.roi_review_status_counts_by_source()`.
- [x] `routes_value_review.py:133` (`duplicates_apply`, self-join op
      `samples`) — verplaatst naar `SamplesMixin.duplicate_pending_matches()`.
- [x] `mapping.py:1004,1017` (`materialize_confirmed_mappings`, stale-
      `mapped_generic`-detectie/-update) — verplaatst naar
      `SamplesMixin.mark_stale_mapped_generic_samples(keep_sample_ids,
      processed_source_ids)`. `processed_source_ids=None` behoudt de
      originele `source_id is None or ...`-kortsluitsemantiek (alle bronnen
      i.p.v. alleen de zojuist verwerkte).
- [x] `dataset.py:124` (`build_dataset`) — verplaatst naar
      `SamplesMixin.accepted_exact_label_samples(extraction_method)` (volle
      rijen, i.t.t. de eerdere `accepted_exact_label_rows()` met 4 kolommen
      voor de format-reviewpagina). **Let op:** twee literal-source-string-
      tests (`test_recognition_model_factory_flow_v3160.py`,
      `test_recognition_open_sources_excluded_v3261.py`) controleerden de
      exacte SQL-tekst in `dataset.py` zelf; aangepast om die tekst in
      `db_samples.py` te controleren (zelfde patroon als eerder toegepast op
      `test_mapping_canonical_gt_v3142.py` in fase 1) — geen gedragswijziging,
      de query verhuisde alleen van bestand.
- [x] `labeler.py:56` (`value_counts`) — verplaatst naar
      `SamplesMixin.roi_correct_status_counts()` (geen
      `extraction_method='mapped_generic'`-filter, i.t.t.
      `mapped_value_review_status_counts()`: de standalone labeler telt over
      alle extractiemethoden).
- [x] `table_cell_training.py:92` (`_current_table_annotations`) —
      verplaatst naar `DetectionReviewMixin.current_table_annotations(source_id)`.
- [x] `table_model_comparison.py:655` (`build_step4_baseline`) — verplaatst
      naar `DetectionReviewMixin.detection_reviews_before_baseline(
      reviewed_at_max, reviewed_at_min)`.

Hiermee zijn alle geïnventariseerde raw-SQL-plekken buiten `db.py`
afgehandeld; item 1 is afgerond.

## Item 2: geometrie/IoU-module

Vóór het verifiëren waren `_intersection_area`/`_area` (`mapping.py`),
`_intersection_area`/`_union` (`mapping_ground_truth.py`) en `_union`
(`generic_detection.py`, `dynamic_locator.py`) 5 onafhankelijke, maar
byte-voor-byte functioneel identieke implementaties (geverifieerd door
letterlijke code-vergelijking vóór het samenvoegen) op 4 plekken. Verplaatst
naar het al bestaande, package-brede `isala_ocr/geometry.py` (dat al
`scale_box()` bevatte en al door `dynamic_locator.py` werd geïmporteerd) in
plaats van een nieuw `training/geometry.py` te maken -- dat zou de opsplitsing
van "1 gedeelde module" naar "2 gedeeltelijk overlappende geometriemodules"
hebben gemaakt, precies het probleem dat dit item moest oplossen.

- `intersection_area(left, right) -> int` (uit `mapping.py`/
  `mapping_ground_truth.py`, identiek).
- `area(box) -> int` (uit `mapping.py`, clamp op minimaal 1).
- `union(boxes) -> Box` (uit `mapping_ground_truth.py`/`generic_detection.py`/
  `dynamic_locator.py`) — de variant met een expliciete lege-lijst-check
  (`generic_detection.py`/`dynamic_locator.py`) is gekozen als canoniek boven
  de kale `min()`/`max()`-versie uit `mapping_ground_truth.py`: dat verandert
  alleen welke foutmelding een reeds-ongeldige aanroep krijgt (een
  `ValueError` met duidelijke tekst i.p.v. `min()`'s eigen "arg is an empty
  sequence"), niet enige uitkomst binnen het geldige bereik.

Alle 4 call-sites importeren de gedeelde functies onder hun oude lokale naam
(`from ..geometry import intersection_area as _intersection_area`, etc.), dus
geen enkele aanroep-plek hoefde te wijzigen. `Iterable` werd een ongebruikte
import in `generic_detection.py`/`dynamic_locator.py` na het verwijderen van
hun lokale `_union`; opgeruimd.

**Bewust NIET meegenomen:** `table_model_comparison.py`'s `_iou`/`_box_area`/
`_coverage_fraction` werken op platte `(x1,y1,x2,y2)`-float-tuples i.p.v.
`Box`, en gebruiken een `1e-9`-epsilon-guard i.p.v. de clamp-op-1 hierboven —
een bewust andere aanpak voor een ander (float, hoog-volume
vergelijkings-)gebruik. Samenvoegen zou de al-getunede
vergelijkingsdrempels die op deze epsilon-semantiek vertrouwen kunnen
verschuiven op randgevallen (zeer kleine/degenererende boxen) — precies het
risico dat het reviewrapport benoemt. Dat vraagt een bewuste
product-beslissing, geen stille eenwording; niet uitgevoerd zonder die
beslissing.

## Item 3: FieldSpec.whitelist-onderzoek

PaddleOCR 3.7.0 (`application/requirements/runtime.txt`) is niet geïnstalleerd
in deze sessie-omgeving, dus de publieke `predict()`/`TextRecognition`-API kon
niet empirisch geverifieerd worden op een runtime-mechanisme om het
karakterdictionary per aanroep te beperken (het zit gebakken in het getrainde
model). Zonder dat te kunnen bevestigen is geen blinde productie-
gedragswijziging doorgevoerd; in plaats daarvan is de gebruiker gevraagd hoe
dit aangepakt moest worden (zie AskUserQuestion in de sessie-transcript).
Gekozen: **post-hoc tekstfilter**.

Nieuw: `ocr/base.py`'s `apply_character_whitelist(text, whitelist)` — strip
tekens buiten de whitelist uit de herkende tekst, met dezelfde intentie als
Tesseract's `-c tessedit_char_whitelist=...` maar toegepast ná herkenning
i.p.v. tijdens decodering (expliciet gedocumenteerd afwijkend gedrag: een
losse verkeerd-herkende 'O' in "12O.5" wordt "12.5", niet de "125" die een
echte cijfer-only-decoder had kunnen gokken).

`ocr/paddle.py` (`PaddleEngine.recognize_many`) en `ocr/recognition.py`
(`PaddleRecognitionEngine.recognize_many`) pasten de `whitelists`-parameter
voorheen weg (`del whitelists`); passen 'm nu toe per input-image via
`apply_character_whitelist()`. `ocr/tesseract.py` blijft ongewijzigd (past
al toe via de tesseract-CLI zelf).

**Dit is een echte productiegedragswijziging**, niet alleen een refactor:
`extraction.py:146` (`_extract_field_values`, de hoofdpijplijn voor vaste-ROI-
velden) geeft `spec.whitelist` al door aan `engine.recognize_many(...)` als
tweede argument — dat werd tot nu toe altijd genegeerd door de
productie-engine. Nieuwe tests toegevoegd:
`tests/test_paddle_input.py::test_whitelist_strips_disallowed_characters_from_recognized_text`
(+ 2 andere) en
`tests/test_recognition_engine.py::test_whitelist_strips_disallowed_characters_from_recognized_text`
(+ 1 andere), die vaststellen dat: (a) een whitelist tekens buiten de set
strip, (b) geen whitelist het gedrag ongewijzigd laat (exacte pariteit met
vóór deze wijziging), (c) `whitelists`/`images` van ongelijke lengte een
duidelijke `ValueError` geeft i.p.v. stilzwijgend fout gedrag.

Volledige testsuite: 723 passed (5 nieuw), 6 failed — de bekende,
onafhankelijke baseline, ongewijzigd.

## Item 4: `_similarity`-functies

`mapping.py._similarity()` (schema-candidate-labelmatching tijdens Mapping)
en `dynamic_locator.py._similarity()` (locator-label-vs-OCR-tekstmatching)
lossen een oppervlakkig vergelijkbaar probleem op, maar met verschillende
normalisatie (`normalize_text()` resp. `normalize_for_matching()`) en
verschillende extra logica (containment-bonus in `mapping.py`; ED/ES/BSA-
domeinguards in `dynamic_locator.py`). **Niet samengevoegd**: dat zou reëel
veldmatchgedrag in productie kunnen verschuiven zonder enige manier om te
verifiëren dat de verschuiving veilig is over de volle breedte van echte
rapporten — hetzelfde risico als bij de IoU-epsilon-kwestie in item 2.

In plaats daarvan: een docstring in beide functies die expliciet naar de
andere verwijst, zodat een toekomstige ED/ES/BSA-bugfix in de ene minstens
zichtbaar maakt dat de andere mogelijk hetzelfde nodig heeft — precies het
"onzichtbaar voor de andere kant"-risico dat het reviewrapport benoemt,
opgelost door het zichtbaar te maken in plaats van de functies te dwingen tot
identiek gedrag. Puur documentatie, geen gedragswijziging.

## Item 5: CLI-duplicatie

Aangepakt (mechanisch, veilig, geen gedragswijziging):

- **Locator-engine-constructie (4x gekopieerd)**: `cli.py`'s
  `_collect_training()`/`_collect_mapping()`/`_run_application_pipeline()` en
  `mapping_gt_cli.py`'s `_collect_mapping()` bouwden elk dezelfde
  `locator_settings`-dict (kopieer `config.ocr`, verwijder
  `active_recognition_model_dir`, zet `recognition_model` uit
  `locator_recognition_model`). Verplaatst naar `cli.py`'s nieuwe
  `_locator_settings(config)`; `mapping_gt_cli.py` importeert 'm.
- **Detectiegate-synclogica (2x letterlijk gekopieerd)**:
  `table_first_cli.py`'s `_sync_table_first_gate()` en `mapping_gt_cli.py`'s
  `_sync_canonical_gate()` berekenden dezelfde ready/reason-tekst en
  schreven 'm naar `TrainingDatabase.set_detection_gate()`. Verplaatst naar
  `training/table_cell_ground_truth.py`'s nieuwe
  `canonical_detection_gate_state()` (berekening) en
  `sync_canonical_detection_gate()` (berekening + persisteren) — een
  training-concern, niet een CLI-concern, dus daar ondergebracht i.p.v. in
  `cli.py`. `table_first_cli.py` behield zijn eigen vroege return (skip als
  er nog geen canonieke GT is); `mapping_gt_cli.py`'s aanroeper kreeg de
  teruggegeven state ongewijzigd.
- **`recognition_gt_cli.py` mist `--log-level`/top-level try-except**: als
  enige van de vier CLI-entrypoints kreeg een `ConfigError` hier voorheen een
  ruwe Python-traceback i.p.v. de nette "log + exit 2" van de andere drie.
  Toegevoegd: `--log-level`-argument, `configure_logging()`-aanroep, en
  hetzelfde `except (ConfigError, FileNotFoundError, KeyError, ValueError,
  RuntimeError): LOGGER.error(...); return 2`-patroon als `cli.py`/
  `mapping_gt_cli.py`. Handmatig gecontroleerd: een niet-bestaand
  configpad geeft nu een nette foutregel + exit-code 2 i.p.v. een
  traceback.

**Bewust NIET aangepakt (gedocumenteerd, niet geforceerd):**

- **`table_first_cli.py`'s eigen, zwakkere argv-scanner** (`_argument_value`)
  naast de echte `argparse`-afhandeling in `cli.py`: bestaat om `--config`/
  `--workspace` te lezen vóórdat de volledige argv wordt doorgegeven aan
  `cli.py`'s eigen parser. Ondersteunt geen `--workspace=pad`-syntax (alleen
  `--workspace pad`) terwijl `argparse` dat wel doet — een echte, kleine
  correctheidsleemte. Herstructureren zodat dit via een echte
  (deel-)argparse-parse loopt is een groter en risicovoller project (kans op
  net-andere randgevallen bij verplichte argumenten/afkortingen) dan de
  andere punten hier; niet uitgevoerd zonder dat apart te doen en te
  verifiëren tegen de echte subcommand-argumenten.
- **Inconsistente exit-codes over cli.py's ~31 subcommands** (bevestigd:
  33 losse `return <int>`-statements): sommige falen met 1, andere met 2,
  evaluatie/vergelijkingscommando's geven bewust altijd 0 terug. Er is geen
  gedocumenteerd contract. Dit zonder volledige audit "rechttrekken" zou het
  risico lopen PowerShell-automatiseringsscripts te breken die mogelijk al
  op een van de huidige (inconsistente) exit-codes vertrouwen voor een
  specifiek subcommand — niet zonder die audit uitgevoerd.

## Item 6: PowerShell-scriptinconsistenties

Aangepakt (mechanisch, geverifieerd tegen het patroon van vergelijkbare,
al-werkende scripts — kon niet empirisch tegen echte Docker draaien in deze
sessie-omgeving):

- **`training-status.ps1` miste de gebruikelijke `$LASTEXITCODE`-check**:
  bevestigd door alle 21 scripts die `docker compose --profile training run`
  aanroepen te controleren — dit was het enige zonder de check. Toegevoegd,
  zelfde patroon als de andere 20 (`if ($LASTEXITCODE -ne 0) { throw ... }`).
- **`--build` vs `--pull never`-inconsistentie**: eerst uitgezocht of dit
  daadwerkelijk willekeurig is of een bewust patroon (`--pull never` na een
  eerdere expliciete `docker compose build` verderop in hetzelfde script, om
  een dubbele rebuild-check te vermijden — dat patroon bestaat wel degelijk,
  bijv. in `train-localization-model.ps1`). Voor 3 plekken bleek het **geen**
  bewust patroon: `build-table-cell-dataset.ps1`/`build-table-region-dataset.ps1`
  (roepen dezelfde `dataset-builder`-service aan als `build-localization-dataset.ps1`,
  dat wél `--build` gebruikt) en `activate-table-cell-model.ps1` (roept
  dezelfde `training-collector`-service aan als `activate-localization-model.ps1`,
  dat wél `--build` gebruikt) — geen van deze drie bouwt die service ergens
  anders expliciet. Dat betekent: een codewijziging zou hier stilzwijgend een
  verouderd gecached image kunnen laten draaien. Rechtgetrokken naar
  `--build`, in lijn met de al-werkende zusterscripts voor dezelfde service.

**Bewust NIET aangepakt (gedocumenteerd, niet geforceerd):**

- **`activate-table-region-model.ps1` implementeert zijn eigen activatielogica
  volledig in raw PowerShell** (leest `model.json`/
  `evaluation_artifacts/test_evaluation.json` rechtstreeks van het
  hostbestandssysteem, schrijft `active.json` rechtstreeks weg) i.p.v. te
  delegeren naar de gecontaineriseerde `model-manager`-tool zoals de andere
  drie `activate-*.ps1`-scripts. Dit is de architectonisch grootste
  inconsistentie uit het rapport en betekent dat een gate-beleidswijziging in
  de containerlogica niet doorwerkt voor table-region-modellen. Een correcte
  fix vereist een nieuwe Python-CLI-subcommand die dezelfde logica binnen de
  container uitvoert plus herschrijving van dit script om daarheen te
  delegeren — een echte productiefunctie-migratie die niet zonder een
  werkende Docker-trainingsomgeving (GPU-modellen, containers) te verifiëren
  is, wat in deze sessie-omgeving niet beschikbaar is. Niet uitgevoerd zonder
  die verificatiemogelijkheid.

## Item 7: JSON-foutrespons-helper

Nieuw: `training/json_api.py` met `json_error(message, status, **extra)` en
`json_body(request)`. Bewust géén `@json_api`-decorator die hele
route-handlers wrapt — elke early-return-validatieguard draagt een eigen
boodschap/statuscode/soms extra velden en is bedrijfslogica om ter plekke te
lezen, geen boilerplate om achter een decorator te verstoppen (zie de
docstring in `json_api.py` voor de volledige motivatie).

Gemigreerd (repo-breed, alle plekken die exact het `{"ok": False, "error":
...}, status`- of `request.get_json(silent=True) or {}`-patroon volgden):
`routes_detection_review.py` (29), `routes_localization_v2.py` (23),
`routes_table_panel_config.py` (6), `routes_mapping_studio.py` (4),
`comparison_review_queue_web.py` (2), `routes_table_region_detect.py` (2),
`routes_detection_lab.py`/`recognition_ground_truth_web.py` (deels — zie
hieronder)/`stale_job_reconciliation.py`/`webui.py` (elk 1).

**Bewust ongemoeid gelaten** (andere vorm, past niet in het gedeelde
contract): `recognition_ground_truth_web.py:301`'s `{"ok": False,
"redirect": ...}, 409` (geen `"error"`-sleutel) en
`routes_mapping_studio.py:99`'s `request.get_json(silent=True) or
request.form` (valt terug op formdata, niet op `{}`).

`json_body()` coerces elke non-dict JSON-body (i.p.v. alleen falsy) naar
`{}` — elke bestaande call site verwachtte al impliciet een dict (roept
altijd `.get(...)` aan), dus een niet-dict body zou al hebben gecrasht;
dit voorkomt die latente crash i.p.v. 'm te reproduceren, zonder enig
bestaand, werkend pad te veranderen.

Geen gedragswijziging voor bestaande paden. Volledige testsuite blijft op
de 6 bekende, onafhankelijke faalpunten (723 passed, 6 failed).

## Status per item

- [x] 1. Raw-SQL-plekken (zie inventaris hierboven)
- [x] 2. Geometrie/IoU-module (zie hieronder)
- [x] 3. FieldSpec.whitelist-onderzoek (zie hieronder)
- [x] 4. `_similarity`-functies (zie hieronder)
- [x] 5. CLI-duplicatie (zie hieronder)
- [x] 6. PowerShell-scripts (zie hieronder)
- [x] 7. JSON-foutrespons-helper (zie hieronder)
- [ ] 8. Overige lage-risico opruimpunten
- [ ] 9. Losse correctheids-signalen
- [ ] 10. Frontend review-studio-unificatie

## Validatieprotocol per stap

1. `python -m pyflakes application/src/isala_ocr` (geen nieuwe ongebruikte
   imports/namen — vergelijk diff tegen de vorige commit, niet alleen de
   absolute lijst).
2. `python -m pytest tests -q` vanuit de repo-root — moet exact op de 6
   bekende, onafhankelijke faalpunten uitkomen (nooit meer, nooit minder):
   - `test_canonical_table_ground_truth_v3131.py::test_step4_template_has_explicit_canonical_gt_mode`
   - `test_clean_root_layout.py::test_operational_content_is_grouped_into_directories`
   - `test_initial_review_visibility_v3137.py::test_hidden_reviewed_candidates_are_not_marquee_selectable`
   - `test_model_comparison_side_by_side.py::test_compare_page_has_new_left_old_right_and_correct_actions`
   - `test_model_comparison_side_by_side.py::test_compare_all_queues_actions_in_required_order`
   - `test_table_model_comparison_v3130.py::test_step7_geometry_exposes_functional_quality_and_accepts_functional_ok`
3. Alleen dan committen en pushen naar `claude/code-review-calls-jc8xyn`.

Als een stap niet zonder twijfel veilig kan (bijv. een productie-
gedragswijziging die niet door een test wordt gedekt, zoals mogelijk bij
item 3): stoppen, de reden hier noteren, en niet doorgaan zonder menselijke
beoordeling. Frontend-werk (item 10) heeft geen equivalent van de
python-testsuite als vangnet — daar extra terughoudend zijn en waar mogelijk
handmatig/visueel verifiëren in plaats van blind te vertrouwen op "het
compileert".
