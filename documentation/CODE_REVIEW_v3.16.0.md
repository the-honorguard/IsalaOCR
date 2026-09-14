# Code review v3.16.0 – architectuur, aanroeppaden en technische schuld

Datum: 2026-09-14

## Scope en aanpak

Op verzoek is de volledige codebase doorgelicht op architectuur en "hoe roepen dingen elkaar aan" (call-graph), niet op een specifieke functionele bug. Vier deelreviews zijn parallel uitgevoerd:

1. Kern-pipeline (`application/src/isala_ocr/*.py`, `ocr/*`, CLI-entrypoints)
2. Training-webapp routing (`training/webui.py`, `training/webui_server.py`, alle `training/routes_*.py`)
3. Training-kernmodules (`training/db.py`, `mapping*.py`, `localization_dataset.py`, `table_model_comparison.py`, …)
4. Frontend (static JS/CSS/templates) en `automation/powershell/*.ps1`

Dit is een **bevindingenrapport**, geen wijzigingenlog: er zijn in deze ronde bewust nog geen fixes doorgevoerd, zodat prioritering eerst kan plaatsvinden. Regelnummers verwijzen naar de staat van de branch op de reviewdatum.

## Samenvatting: is de indruk "het is een zooitje" terecht?

Grotendeels ja, met nuance. De **kernpipeline** (`cli.py → pipeline.py → extraction/study_info/consistency/output → ocr/*`) is verrassend schoon en lineair. De schuld zit vooral in de **trainingsmodule** (27.151 regels, 68 bestanden) die organisch is gegroeid: een 3076-regelige God-class (`db.py`), een 4079-regelig bestand dat voor 93% uit één functie bestaat (`webui.py`), meerdere bijna-identieke bestandsparen die uit elkaar zijn gegroeid (`mapping.py`/`mapping_fast.py`), en aan de frontend-kant vier onafhankelijk gebouwde "review studio"-implementaties die allemaal hetzelfde probleem oplossen. Niets hiervan is per se incorrect, maar het onderhoudsrisico is hoog en al minstens één plek (zie **Hoog** hieronder) heeft aantoonbare functionele drift tussen twee bijna-identieke code-paden.

---

## Hoog – functionele drift tussen bijna-identieke code-paden

### `mapping.py` vs. `mapping_fast.py`: bugfix geldt niet voor alle strategieën

`training/mapping.py:210` (`suggest_mappings`) en `training/mapping_fast.py:15` (`suggest_mappings_fast`) zijn geen kopieën van elkaar maar een **echte fork**: `suggest_mappings_fast` bevat nieuwere logica die in de oude versie ontbreekt (lateral-ambiguïteitsfilter, "exact-alias"-disambiguatie om verkeerde labeltoewijzing bij gelijke eenheid te voorkomen — `mapping_fast.py:54,100-144,107,154`). Beide functies worden nog steeds in productie aangeroepen, afhankelijk van een strategie-vlag:

```python
# collector.py:743-746
suggest_mappings_fast(...) if strategy == "table_first" else suggest_mappings(...)
```

**Gevolg:** de lateral-ambiguïteitsfix werkt alleen bij `strategy == "table_first"`; elke andere strategie krijgt stilzwijgend de oudere, minder veilige scoring. Dit is geen stijlkwestie maar een reëel functioneel risico — aanbevolen actie: uitzoeken of de oude `suggest_mappings` nog een bestaansreden heeft, en zo niet, de nieuwe logica de enige maken (of expliciet documenteren waarom beide moeten blijven bestaan).

### `mapping_ground_truth.py` vs. `mapping_ground_truth_fast.py`: dezelfde functienaam, twee lichamen

Beide bestanden definiëren `collect_mapping_from_canonical_gt` (resp. `mapping_ground_truth.py:245` en `mapping_ground_truth_fast.py:160`). Alleen de `_fast`-versie wordt ergens geïmporteerd (`mapping_gt_cli.py:14`); de oude versie is dode code maar het bestand zelf is niet dood — `collector.py:31` importeert nog wél `canonical_table_regions`/`mark_canonical_geometry` uit hetzelfde bestand. Dit "half dood, half levend"-patroon is foutgevoelig bij toekomstig onderhoud.

### Geometrie/IoU-berekeningen 4× onafhankelijk opnieuw geïmplementeerd, met afwijkende semantiek

- `mapping.py:448,454` — eigen `_intersection_area`/`_area`, area geclamped op minimaal `1`
- `mapping_ground_truth.py:52,132` — eigen `_intersection_area`/`_union`
- `table_model_comparison.py:74,95` — eigen `_iou`/`_box_area`, epsilon-guard (`1e-9`) i.p.v. clamp
- `generic_detection.py:127` en `dynamic_locator.py:51` — nog twee eigen `_union`-implementaties

Er is geen gedeelde geometriemodule (`metrics.py` bevat alleen tekst/OCR-metrics, geen IoU). Omdat de "area"-semantiek verschilt (clamp op `1` vs. epsilon `1e-9` vs. geen guard), kunnen deze implementaties op randgevallen (zeer kleine/degenererende boxen) verschillende uitkomsten geven. Een fix voor degenererende boxen in één bestand plant zich niet automatisch voort naar de andere drie.

### Twee onafhankelijk getunede fuzzy-matchfuncties, beide `_similarity` genoemd

`mapping.py:175` (SequenceMatcher + containment-bonus) en `dynamic_locator.py:71` (eigen normalisatie + expliciete ED/ES/BSA-penalty's) lossen hetzelfde "is dit hetzelfde veld"-probleem op, maar zijn los van elkaar getuned. Een bugfix voor bijv. ED/ES-verwarring in `dynamic_locator.py` is onzichtbaar voor de `mapping.py`-kant.

---

## Hoog – architectuur van de trainings-webapp (`training/`)

### `db.py` (3076 regels) is één God-class met 94 methoden

`TrainingDatabase` (`db.py:43`) bevat schema-migratie (hand-rolled inline SQL, geen versiebeheerde migratiebestanden, `db.py:271-652`), samples, veldschema's, generieke detecties, relaties/feedback, mappings, mappingprofielen, detectiekandidaten/annotaties/reviews, localization-datasets/-evaluaties/-modellen én de detectiegate — allemaal in één klasse. Elke wijziging aan één subsysteem raakt potentieel de hele klasse.

Bovendien wordt op **12+ plekken buiten `db.py`** rechtstreeks raw SQL tegen dezelfde tabellen uitgevoerd in plaats van via een `TrainingDatabase`-methode: `table_quality.py:74-103`, `webui.py:914-1085` (6×), `recognition_ground_truth_web.py:29-33,53-56`, `recognition_ground_truth.py:305,439,445`, `routes_roi_review.py:34-42`, `routes_value_review.py`, en `projects.py:401-449` die zelfs een **eigen `sqlite3.connect()`** opent om paden in `localization_models`/`localization_evaluations` te herschrijven (met een silent `except sqlite3.OperationalError: pass` — een schemawijziging in `db.py` breekt dit onopgemerkt).

**Aanbeveling:** nieuwe/ontbrekende aggregatiequery's (bijv. de twee in `routes_roi_review.py`/`routes_value_review.py`) als methode aan `TrainingDatabase` toevoegen in plaats van raw SQL in de weblaag; op termijn migratie naar een versiebeheerd migratiesysteem.

### `webui.py` (4079 regels): 93% is één functie, met drie routing-mechanismen door elkaar

- Regels 296–4079 zijn vrijwel volledig `create_web_app()`. Daarbinnen is `/process/<step_key>` (regels 2954–3936, ~980 regels) één functie met 18+ `elif step_key == "..."`-takken voor totaal ongerelateerde wizardstappen.
- Routes worden op **drie verschillende manieren** geregistreerd: (A) direct in `create_web_app` gedefinieerd, (B) via ~18 `register_<naam>_routes(app, **closures)`-aanroepen aan het eind van dezelfde functie, (C) *na* het teruggeven van de app, vanuit `webui_server.py:main()` (regels 113-124) die nóg vier routes bolt (`install_recognition_ground_truth_review`, `install_comparison_review_queue`, `install_job_cancellation`, `install_stale_job_reconciliation`).
- **Concreet risico:** `create_web_app()` heeft precies één aanroeper (`webui_server.py:114`) en geen enkele test roept hem aan. Elke toekomstige embedding (test, ander WSGI-entrypoint) die alleen `create_web_app()` gebruikt, verliest stilzwijgend job-cancellation, recognition-GT-review, de comparison-queue en stale-job-herstel — zonder foutmelding.
- `registry.py` staat in dezelfde map als `routes_*.py`/`webui_server.py`, maar heeft niets met routing te maken (het is een modelregistratie-helper voor de losse `isala-ocr` CLI, `registry.py:28,66`). Verwarrende naam op een verwarrende plek.

**Aanbeveling:** minimaal (a) alle vier "post-hoc install"-aanroepen verplaatsen in `create_web_app()` zelf zodat er één samenhangend app-object ontstaat, (b) `registry.py` hernoemen/verplaatsen weg uit de webapp-map, (c) de `/process/<step_key>`-dispatcher opsplitsen per stap.

### Geen gedeelde JSON-foutrespons-helper in de Flask-routes

Het patroon `{"ok": False, "error": "..."}, <status>` en `request.get_json(silent=True) or {}` staat losstaand gekopieerd in tientallen route-handlers (o.a. 24× in `routes_detection_review.py`, 18× in `routes_localization_v2.py`). Een kleine `@json_api`-decorator of helperfunctie zou dit centraliseren.

---

## Middel – dubbele/verweesde CLI- en scriptlogica

- **Locator-engine-constructie 4× gekopieerd** (`cli.py:198-208,231-236,276-282`, `mapping_gt_cli.py:92-99`) — inclusief hetzelfde hardcoded default-modelstring `"PP-OCRv6_small_rec"`, dat in totaal **5× hardcoded** voorkomt (ook in `ocr/recognition.py:99,130`).
- **Detectiegate-synclogica letterlijk gekopieerd** tussen `table_first_cli.py:39-80` en `mapping_gt_cli.py:36-59`, inclusief identieke reden-strings.
- `table_first_cli.py:28-36` implementeert een **eigen, zwakkere argv-scanner** naast de echte `argparse`-afhandeling in `cli.py`/`mapping_gt_cli.py` — twee filosofieën voor dezelfde opties.
- `recognition_gt_cli.py` heeft als enige van de vier CLI-entrypoints **geen** `--log-level` en **geen** top-level try/except: een `ConfigError` geeft hier een ruwe Python-traceback i.p.v. de nette "log + exit 2" die de andere drie bieden.
- **Inconsistente exit-codes** over de ~31 subcommands van `cli.py`: sommige falen met 1, andere met 2, sommige (evaluatie/vergelijking) geven bewust altijd 0 terug — er is geen gedocumenteerd contract.
- **`FieldSpec.whitelist` is een no-op in productie:** `ocr/paddle.py:141` en `ocr/recognition.py:197` gooien de per-veld whitelist weg (`del whitelists  # PaddleOCR gebruikt eigen dictionary`), terwijl `ocr/tesseract.py` hem wél toepast. Omdat PaddleOCR de productie-engine is, doet een in het profiel geconfigureerde whitelist dus niets — makkelijk te missen bij het afstellen van een veld.
- **PowerShell:** de vier `activate-*-model.ps1`-scripts zijn architectonisch inconsistent — drie delegeren naar een gecontaineriseerde Python-tool, `activate-table-region-model.ps1` implementeert de hele activatielogica zelf in raw PowerShell (eigen paddcontrole, `active.json` direct wegschrijven, geen Docker-aanroep). Een gate-beleidswijziging in de containerlogica werkt dus niet door voor table-region-modellen. Ook: `--build` vs. `--pull never` wisselt inconsistent tussen verder identieke `build-*-dataset.ps1`/`activate-*.ps1`-scripts, en `training-status.ps1` mist als enige de gebruikelijke `if ($LASTEXITCODE -ne 0) { throw }`-check.

---

## Middel – frontend: vier keer hetzelfde "review-studio"-patroon opnieuw gebouwd

`mapping-review-studio.js` (748 regels, vanilla DOM), `step7-review-flow.js`+`step7-single-panel.js` (409+454 regels, vanilla DOM met andere architectuur), de `react/*.js`-familie (React), en de 77 KB inline `<script>` in `templates/detection_review_studio.html` zijn **vier onafhankelijk gebouwde implementaties** van in essentie hetzelfde scherm: afbeelding + boxen + zoom/pan + toetsenbord-shortcuts + optimistic UI met rollback bij mislukte save. Elk heeft een **eigen retry/foutafhandelingsstrategie** voor het opslaan van reviewbeslissingen (FormData+HTML-scraping, JSON+headers, fetch-monkeypatch-met-queue, en nog een vierde queue-implementatie inline). Een bugfix in de ene studio verschijnt niet automatisch in de andere drie.

Daarnaast: twee onafhankelijke pollinglussen tegen `/api/status` op elke pagina (`app.js` én `job-runtime.js`, die elkaars events al deels beluisteren maar toch los blijven pollen), en drie React-paginacontrollers (`react/localization-artifacts.js`, `react/localization-quality.js`, `react/localization-workbench.js`) met bijna letterlijk gekopieerde format-helpers en poll/error-boundary-scaffolding — ook al terug te vinden in de TypeScript-bron (`frontend/src/*.ts`), dus geen build-artefact maar echte broncode-duplicatie.

---

## Laag – dode code en losse eindjes

- `ocr/table_structure.py:1031-1112` (`detect_panels_with_benchmark`) wordt nergens aangeroepen; het bestand bevat daarnaast expliciet als "tijdelijk lab-tool" gedocumenteerde methoden (`table_structure.py:806-962`, "Probeer 2"/"Probeer 3") die permanent in de productie-engine-klasse zijn blijven staan.
- `static/react/gt-studio.js` + `templates/gt_studio.html` zijn in de praktijk onbereikbaar: alleen zichtbaar via een `?view=`-querystring die nergens in de app wordt opgebouwd (`routes_detection_review.py:280-289`) — een tweede, onderhouden-noch-verwijderde implementatie van een scherm dat `detection_review_studio.html` al dekt.
- Ongebruikte imports (bevestigd met pyflakes): `extraction.py:5`, `ocr/paddle.py:3`, `ocr/recognition.py:4`, `ocr/table_structure.py:6`.
- `DocumentResult.errors` (`models.py:108`) wordt in `pipeline.py` altijd op `[]` gezet en nooit gevuld — staat wel in elke `result.json`, maar is functioneel dood.
- `FieldSpec.panel`/`FieldSpec.screen_labels` (`config.py:27-28`) worden alleen door `training/*` gebruikt, niet door de kern-extractiepijplijn.
- `collector.py:129` (`_files`), `localization_dataset.py:31-33` (`_split_for_source`, expliciet "deprecated" in eigen docstring) en `localization_dataset.py:223-230` (`_context_patch_box`) hebben nul aanroepers.
- `mapping_ground_truth.py:245`'s `collect_mapping_from_canonical_gt` is volledig vervangen door de `_fast`-versie (zie Hoog hierboven) en heeft geen aanroepers meer.
- Permanent uitgeschakelde maar nog geregistreerde endpoints: `routes_detection_review.py:471-483` geeft alleen nog `410 Gone` terug.

---

## Losse correctheids-signalen (geen diepe bug-hunt, wel opgevallen)

- `consistency.py:35` gebruikt `assert` om `None`-waarden vóór een berekening af te vangen — asserts verdwijnen onder `python -O`; als dat ooit gebruikt wordt, kan een `None` alsnog een onbehandelde `TypeError` veroorzaken.
- `validation.py:76-80` heeft een hardcoded eenheids-aliastabel voor precies twee eenheidsfamilies (`mlm2`, `lmin`); een nieuw veld met een andere eenheid krijgt geen vergelijkbare OCR-tolerantie.
- `ocr/paddle.py:163-168` bevat een 4-kanaals-afbeeldingsafhandeling die in de praktijk nooit bereikt wordt, want alle upstream-decoders (`image_io.py`, `dicom.py`) leveren altijd 3 kanalen — ongeteste aanname die bij eventuele toekomstige input-varianten voor het eerst getest wordt in productie.
- `recognition_ground_truth_web.py:23` gebruikt een process-lifetime `ThreadPoolExecutor(max_workers=1)` voor fire-and-forget rebuilds; falen binnen die taak is nergens zichtbaar (geen `.result()` wordt ooit opgevraagd).
- `routes_jobs.py:155-190` (`retry_job`) dupliceert de job-queue-schrijflogica handmatig in plaats van de bestaande `enqueue_job`-closure te hergebruiken die `create_job` wel gebruikt.

---

## Aanbevolen prioritering (indien gewenst als vervolgstap)

1. **Nu oppakken:** de `mapping.py`/`mapping_fast.py`-strategiesplitsing uitzoeken — dit is de enige bevinding met aantoonbaar verschillend functioneel gedrag tussen twee actieve code-paden.
2. **Op korte termijn:** `webui_server.py`'s vier post-hoc route-installs in `create_web_app()` zelf onderbrengen, zodat er één betrouwbare manier is om de webapp te bouwen.
3. **Structureel, gefaseerd:** `db.py` en `webui.py` opsplitsen per subsysteem/stap; een gedeelde geometrie-/IoU-module invoeren; één "review studio"-basiscomponent voor de vier frontend-implementaties.
4. **Opruimen (laag risico):** de dode code hierboven verwijderen, ongebruikte imports opschonen, `registry.py` hernoemen/verplaatsen.

Dit rapport bevat bewust nog geen code-wijzigingen. Laat weten welke punten als eerste opgepakt moeten worden — gezien de omvang (27k+ regels alleen al in `training/`) is dit geen taak voor één sessie.
