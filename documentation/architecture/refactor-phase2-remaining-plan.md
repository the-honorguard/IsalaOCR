# Fase 2 — resterende punten: wat nodig is en hoe

Dit document beschrijft de drie punten die in `refactor-phase2-plan.md`
bewust zijn opengelaten, met per punt: waarom het is opengelaten, wat ik
nodig heb om het alsnog te doen, en de concrete stappen. Doel: dit kan als
los vervolgtraject worden opgepakt (in deze of een volgende sessie) zonder
opnieuw te hoeven uitzoeken wat er nodig is.

---

## 1. Frontend: de drie "echte" review-studio's unificeren

(`mapping-review-studio.js`, `step7-review-flow.js`+`step7-single-panel.js`,
de inline `<script>` in `detection_review_studio.html`. Zie
`refactor-phase2-plan.md`, item 10, voor de volledige analyse van de vier
implementaties en waarom de React-familie er niet bij hoort.)

### Waarom opengelaten
Geen geautomatiseerde regressietest zoals de rest van dit hele plan had
(723 pytest-tests aan de Python-kant). Elke wijziging aan zoom/pan,
sneltoetsen of de retry/rollback-logica is alleen interactief in een browser
te verifiëren.

### Wat ik nodig heb — geverifieerd beschikbaar
Ik heb dit al gecontroleerd in deze sessie-omgeving, dus dit is geen
aanname:
- **Een lokale dev-server voor de trainings-webapp draait zonder Docker/GPU.**
  `create_web_app()` importeert en start volledig zonder PaddleOCR
  geïnstalleerd (bevestigd) en de bestaande testsuite bootst 'm al op met
  een minimale tijdelijke workspace (`tests/test_webui_activity_dock.py`'s
  `make_app(tmp_path)`-patroon: alleen een lege `project/VERSION`-file en
  wat lege mappen nodig). `webui_server.py` draait op `waitress`, dat al
  geïnstalleerd is.
- **Chromium is beschikbaar** (`/opt/pw-browsers/chromium`). Python's
  `playwright`-package zelf staat nog niet in de omgeving, maar is een
  gewone `pip install playwright` (de browserbinaries hoeven niet opnieuw
  gedownload te worden — dat is al geregeld via
  `PLAYWRIGHT_BROWSERS_PATH`/`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD`).
- **Fixture-data**: de drie schermen hebben ieder wat databasegevulling nodig
  om iets te tonen (detectiekandidaten, table-compare-issues, mapping-
  relaties). Ik bouw dit met de bestaande `TrainingDatabase`-methodes (nu
  allemaal in `db_*.py`-mixins, dus rechtstreeks aan te roepen) i.p.v. een
  echte DICOM-pijplijn te draaien — sneller en al hoe de bestaande
  `tests/test_*review*.py`-fixtures dit ook doen.

### Wat ik NIET heb en moet vragen zodra het zover is
- ✅ **Productbeslissing genomen**: de `localStorage`-queue van
  `detection_review_studio.html` (rijkste retry/backoff/dedup-semantiek)
  wordt de gedeelde standaard. `mapping-review-studio.js` en `step7-*.js`
  krijgen daardoor bewust zichtbaar ander foutgedrag dan nu (geen
  automatische rollback meer, wel een "Opnieuw"-knop bij een definitief
  mislukte poging) — dit is akkoord, dus stap 5 hoeft niet meer te wachten.
- ✅ **Akkoord op screenshots/opnames** van de trainings-webapp met
  synthetische fixture-data — al gebruikt voor de nulmeting hierboven.
- ✅ **Route-beslissing genomen**: `mapping-review-studio.js` wordt
  gerefactored op zijn bestaande, bereikbare route (`/mapping/<source_id>`,
  `mapping_studio.html`) zoals gepland; het feit dat de hoofdflow er niet
  naartoe wijst wordt in dit traject niet apart gerepareerd (dat is een
  eigen, ongerelateerd product/UX-besluit over routing, geen
  studio-infrastructuur).

### Stappen (per stap: bouwen → in de browser testen → pas dan committen)
1. ✅ **Afgerond.** Fixture-workspace + minimale config geschreven als
   scratchpad-script (niet meegecommit, zoals gepland — leeft alleen in de
   sessie-omgeving onder `/tmp/.../scratchpad/studio_baseline/`), dat elk
   van de drie schermen vult met genoeg data om te tonen en te bewerken:
   - `detection-review/source-detect`: 8 `table_cell`-kandidaten +
     1 handmatige annotatie via `replace_localization_detection()` /
     `add_detection_annotation()`.
   - `mapping/source-map`: 1 veld (`lv_ef`) + 1 label/waarde-relatie via
     `seed_field_definitions()` / `replace_generic_detection()`, plus een
     reviewed detection-annotation die exact het waardeblok dekt — nodig
     omdat `routes_roi_mapping_studio.py` een relatie alleen toont als
     `pipeline_a_roi_ready` waar is (elke relatie zonder een corresponderende
     Pipeline-A-annotatie/kandidaat wordt **stil weggefilterd**, geen fout).
   - `process/table-compare`: een volledige baseline-vs-current-run opzet
     (canonieke dataset + `detection_reviews`-rij als bevroren Stap-4-GT +
     `localization_detections/<source>.json` als "huidige" Stap-8-run +
     `table_cell_models/active.json`), 1-op-1 naar het patroon van
     `tests/test_table_model_comparison_v3130.py::_seed_dataset`/
     `_seed_baseline_and_current` — zonder dat opzet toont deze pagina geen
     enkel comparison-panel (`open.count == 0` → `display:none`).
   `create_web_app()` + `waitress.serve` lokaal gestart op
   `127.0.0.1:8099`.

   **Onverwachte bevinding tijdens het opzetten** (geen actie nodig, wel
   relevant voor toekomstig werk aan deze schermen): een workspace-pad van de
   vorm `<root>/training/workspace` wordt door zowel `webui.py`'s
   `workspace_root()` als door `table_model_comparison.py`/
   `table_cell_training.py` (via `resolve_project_workspace()`) herschreven
   naar `<root>/training/workspace/projects/<actief-project-id>/` —
   `TrainingDatabase` zelf doet dat niet. Bij een verse workspace migreert
   `ProjectManager._initialize()` bestaande data (o.a. `samples.sqlite3`,
   `source_renders/`, `localization_detections/`) automatisch naar die
   project-map zodra hij voor het eerst wordt aangemaakt, maar **niet**
   `table_cell_datasets/` en `table_cell_models/` — die twee ontbraken in de
   migratie-lijst. Voor deze nulmeting opgelost door alle fixture-data direct
   in het al-opgeloste projectpad te schrijven (`resolve_project_workspace()`
   zelf aanroepen vóór het seeden). Geen fix nodig aan de productiecode
   hiervoor — dit is een scratchpad-only workaround — maar de ontbrekende
   paden in de migratielijst zijn wel een reëel klein risico voor een echte
   platform-upgrade-migratie en zijn het vermelden waard als los, apart
   op te pakken puntje (niet in scope van dit unificatietraject).
2. ✅ **Afgerond — nulmeting vastgelegd.** Playwright (Python sync API,
   headless Chromium) heeft alle drie schermen bezocht en 19 screenshots +
   een vaste interactiesequentie vastgelegd:
   - **detection-review**: initiële staat, muiswiel-zoom in/uit, spatie+
     slepen pannen, `F` (fullscreen review-mode — nodig omdat de kandidatenlijst
     en de zoom-/view-knoppen in de "quick review"-inline-laag altijd
     `display:none` staan via een unconditionele `<style>`-regel in
     `detection_review_studio.html` totdat focus-mode actief is), een
     kandidaatbox selecteren, en een geforceerd mislukte save (`page.route`
     abort op `/api/detection-review/**`, sneltoets `C` = "Includeren") —
     de reviewqueue-retry-UI is zichtbaar in het resultaat.
   - **mapping ROI-studio**: bevestigd dat dit scherm alleen via
     `/mapping/<source_id>` (niet `/mapping-labels/<source_id>`, zie de
     bevinding hieronder) een werkende `mapping-review-studio.js`-overlay
     toont; `F` opent 'm, muiswiel/knoppen zoomen, `P` + slepen pant,
     pijltjestoets navigeert, `Enter` probeert goed te keuren (blokkeert
     hier op "kies eerst een functioneel veld" — geen save-call, dus de
     geforceerde route-abort had in dit specifieke geval geen zichtbaar
     effect; voor een volgende nulmeting eerst een functioneel veld
     selecteren voordat Enter wordt gebruikt).
   - **table-compare**: initiële staat met een echt zichtbaar
     comparison-panel en 1 open afwijking (FP), paneelnavigatie via
     `J`/`K`.
   - Screenshots + het seed-/serve-script zijn scratchpad-only (niet
     meegecommit, zoals gepland) en dus niet blijvend beschikbaar na deze
     sessie; de bevindingen hierboven en de aanpak zijn hier vastgelegd zodat
     een volgende sessie de nulmeting in enkele minuten kan reproduceren.

   **Onverwachte bevinding (relevant voor de scope van dit traject)**:
   `mapping-review-studio.js`'s activatie-guard (`if (!rows.length || ...)
   return;`) faalt stil op `/mapping-labels/<source_id>` — de pagina die de
   hoofdflow (stap-voor-stap-wizard, `/mapping`- en
   `/mapping-labels`-index-redirects) daadwerkelijk aanstuurt — omdat
   `mapping_labels_studio.html` de vereiste `.mapping-relation-row`-DOM niet
   rendert. De derde "echte" studio-implementatie is dus in de praktijk
   alleen bereikbaar via de oudere `/mapping/<source_id>`-route
   (`mapping_studio.html`, via `generic_detection.html`'s "Naar
   mappingstudio"-link vanaf `/detections`), niet via de huidige hoofdroute.
   Voorgelegd en beantwoord: unificeren op de bestaande `/mapping/<id>`-route
   (zie hierboven); de hoofdflow-routing wordt in dit traject niet apart
   aangepast.
3. ✅ **Afgerond.** De pan-sleepmechaniek (pointerdown/move/up →
   `scrollLeft`/`scrollTop`-delta, incl. pointer-capture) was byte-voor-byte
   bijna identiek tussen `mapping-review-studio.js` en de inline
   detection-review-script; geëxtraheerd naar
   `static/viewport-pan.js` (`IsalaViewportPan.createDragPan`, gewone
   browser-global zoals de rest van deze scripts — geen bundelaar hier). Elk
   scherm behoudt zijn eigen trigger-conditie (spatie+slepen vs.
   pan-mode-knop vs. middelste muisknop) en event-fase/`stopPropagation`-keuze
   als expliciete opties, want die verschillen bewust per scherm (detection-
   review's viewport heeft ook box-tekenen/-selecteren op dezelfde
   pointer-events, mapping niet).
   Geladen via een nieuwe `<script>`-tag in `base.html`'s `<head>` (niet
   onderaan bij de andere static-scripts) — de detection-review-inline-script
   staat middenin `{% block content %}` en wordt dus al uitgevoerd vóórdat de
   scripts onderaan de pagina laden; in `<head>` laden garandeert
   beschikbaarheid vóór welke `{% block content %}` dan ook.
   De **zoom-schaalwiskunde zelf bleef bewust ongemoeid**: de twee schermen
   berekenen zoom conceptueel anders (detection-review: absolute
   percentage-breedte met cursor-anchoring; mapping: multiplier over een
   "fit"-basisschaal, altijd viewport-center-behoudend, geen
   cursor-anchoring) — dat samenvoegen zou een zichtbare gedragswijziging
   zijn, geen neutrale extractie, en hoort dus niet in deze laagrisico-stap.
   Twee bestaande literal-string-tests
   (`tests/test_detection_zoom_busy_v3811.py`,
   `tests/test_mapping_review_pan_v31412.py`) verwezen naar de oude
   inline-pan-code; bijgewerkt naar de nieuwe `IsalaViewportPan.createDragPan`
   call-sites. Geverifieerd: volledige pytest-suite blijft op dezelfde 6
   vooraf bekende, ongerelateerde faalpunten; een Playwright-nulmeting-rerun
   op alle drie schermen leverde 19 screenshots op, 16 byte-identiek aan de
   nulmeting en de overige 3 (wheel-zoom-stappen in detection-review) visueel
   ononderscheidbaar (muispositie-/timingjitter tussen losse browserruns,
   geen DOM-verschil).
4. ✅ **Afgerond.** De percentage-box-overlay-positionering
   (pixelcoördinaten + natuurlijke afbeeldingsgrootte → CSS-percentages) was
   niet alleen tussen de twee bestanden gedupliceerd, maar ook *binnen*
   `detection_review_studio.html` zelf op 4 plekken (`setCoords`,
   `syncMarker`, `renderRasterPreview`, `appendManualAnnotation`) naast
   `mapping-review-studio.js`'s `setBox`. Geëxtraheerd naar
   `static/box-overlay.js` (`IsalaBoxOverlay.applyBoxRect`/
   `applyPointPosition`), zelfde laadplek als `viewport-pan.js`. Elk
   call-site behield zijn eigen validatie/clamping/hide-on-invalid-gedrag
   (dat verschilt bewust per plek); alleen de coördinatenwiskunde en de
   uiteindelijke style-toewijzing zijn gedeeld. Geverifieerd: pytest blijft
   op dezelfde 6 bekende faalpunten (geen enkele literal-string-test brak
   deze keer), en de nulmeting-rerun leverde 18/19 screenshots
   byte-identiek op (de 19e verschilt 1 byte, consistent met
   render-jitter, geen DOM-verschil).
5. De gedeelde retry-queue-primitive, gemodelleerd naar de
   `localStorage`-queue (akkoord, zie hierboven), met URL-opbouwer en
   optimistic-apply/-rollback-callbacks als expliciete parameters per scherm.
6. Wat bewust NIET wordt aangeraakt: elk scherm's eigen datamodel ("wat is
   een box") en backend-routevorm — dat hoort bij het domeinobject van dat
   scherm, niet bij de studio-infrastructuur.
7. Na elke stap: dezelfde nulmeting-interactiesequentie opnieuw uitvoeren op
   alle drie schermen (niet alleen het scherm dat net veranderde — de
   primitives worden gedeeld), screenshots vergelijken, pas dan naar de
   volgende stap.

---

## 2. CLI: argv-scanner in `table_first_cli.py` + inconsistente exit-codes

(Zie `refactor-phase2-plan.md`, item 5, "Bewust NIET aangepakt".)

### Status: exit-codes uitgevoerd; argv-scanner nog open

**De audit is uitgevoerd** (alle 30 subcommands' `return`-paden
geëxtraheerd met `ast`, gekruist tegen elk `automation/powershell/*.ps1`-
script dat `$LASTEXITCODE` controleert). Belangrijkste bevinding:
**geen enkel script controleert ooit een specifieke waarde (1 vs. 2) — elk
script checkt uitsluitend `-ne 0`.** Dat maakt normaliseren van de
exit-codes zelf risicoloos voor de bestaande automatisering.

Gevonden contract (nu ook dat consistent, en dat is ook zo gedocumenteerd in
`cli.py`'s `main()`-docstring):
- **0** = success.
- **1** = draaide volledig, maar met een data-kwaliteitsprobleem (niet een
  bug) — al zo bij `process`, `collect-training`, `collect-mapping`,
  `apply-mappings`, `read-mapped-values`.
- **2** = kon niet eens draaien (configuratie/argumentfout, of een
  onbehandelde `ConfigError`/`FileNotFoundError`/`KeyError`/`ValueError`/
  `RuntimeError` die naar `main()`'s catch-all doorstroomt).

Twee subcommands weken hiervan af en zijn rechtgetrokken:
`validate-localization-dataset`/`validate-table-cell-dataset` gaven bij een
niet-valide dataset exit-code **2** (hergebruikte de "kon niet draaien"-code
voor een normale, verwachte uitkomst) i.p.v. **1** (zoals de andere
data-kwaliteit-uitkomsten). Beide scripts die deze subcommands aanroepen
(`validate-localization-dataset.ps1`/`validate-table-cell-dataset.ps1`)
checken ook hier alleen `-ne 0`, dus geen enkel automatiseringspad
verandert van gedrag.

`table_first_cli.py`'s argv-scanner (stap 4 hieronder) is nog niet
aangepakt — dat blijft een aparte, grotere herstructurering.

### Waarom opengelaten
`table_first_cli.py`'s eigen argv-scanner herstructureren naar echte
argparse raakt hoe elke subcommand wordt aangeroepen; de exit-codes over
~31 subcommands van `cli.py` rechttrekken zonder te weten wat de
PowerShell-automatisering per subcommand aan exit-code verwacht, kan
`$LASTEXITCODE`-checks in `automation/powershell/*.ps1` stil laten breken.

### Wat ik nodig heb
- **Geen nieuwe tool/omgeving** — dit kan volledig met wat al beschikbaar is
  (Python, pytest, tekstueel doorzoeken van de `.ps1`-scripts). Dit is dus
  het makkelijkst van de drie om alsnog te doen, mits ik het grondig
  uitzoek in plaats van gok.
- **Tijd voor een volledige audit**, niet een steekproef: voor elk van de
  ~31 subcommands van `cli.py` opzoeken (a) welke exit-codes het nu
  daadwerkelijk kan retourneren, en (b) of en hoe een `.ps1`-script
  `$LASTEXITCODE` daarna gebruikt (`-eq`/`-ne`/specifieke waarde, of alleen
  "niet-nul is fout").

### Stappen
1. **Inventariseren, niet wijzigen**: script dat voor elke `_xxx`-functie in
   `cli.py` alle `return <int>`-paden extraheert (met de omringende
   voorwaarde) in een tabel: subcommand → mogelijke exit-codes → betekenis.
2. Voor elke `automation/powershell/*.ps1` die naar een `isala_ocr.cli`-
   subcommand verwijst: de exacte `$LASTEXITCODE`-check ernaast leggen.
3. Pas daarna een target-contract voorstellen (bijv. "0 = succes, 1 =
   gedeeltelijk mislukt/data-issue, 2 = configuratie-/argumentfout" — in
   lijn met wat `main()` nu al doet voor `ConfigError`/`ValueError`/etc.)
   en per subcommand list welke een wijziging nodig hebben.
4. `table_first_cli.py`'s argv-scanner — **het kleine bugfixje is
   afgerond**: `_argument_value()` ondersteunt nu ook `--workspace=pad`/
   `--config=pad` naast de bestaande `--workspace pad`-vorm (6 nieuwe tests
   in `tests/test_table_first_cli_argument_value.py`). De grotere
   herstructurering (dit hele pre-scan-mechanisme vervangen door een echte
   argparse-parse) blijft open — dat vraagt nog steeds de stap 1-3-audit
   hierboven om zeker te weten dat geen enkel script op een andere,
   impliciete parsing-nuance leunt.
5. Voor elke wijziging: bestaande CLI-tests (`tests/test_*cli*.py`) plus een
   gerichte nieuwe test per aangepast subcommand; nooit een exit-code
   wijzigen zonder een test die het oude én nieuwe gedrag vastlegt.

---

## 3. `activate-table-region-model.ps1` naar de gecontaineriseerde tool migreren

(Zie `refactor-phase2-plan.md`, item 6, "Bewust NIET aangepakt".)

### Waarom opengelaten
Dit script doet nu zijn eigen activatielogica in raw PowerShell (leest
`model.json`/`evaluation_artifacts/test_evaluation.json` van het
hostbestandssysteem, schrijft `active.json` weg) i.p.v. te delegeren naar de
`model-manager`-tool zoals de andere drie `activate-*.ps1`-scripts. Een
correcte fix is een echte productiefunctie-migratie: een nieuwe Python-CLI-
subcommand die dezelfde logica in de container uitvoert, plus herschrijving
van het script om daarheen te delegeren.

### Wat ik nodig heb — en niet heb in deze sessie-omgeving
- **Een werkende Docker-trainingsomgeving** (de `training`-profile services
  uit `docker-compose`, incl. het `model-manager`-image) om de nieuwe
  subcommand daadwerkelijk te draaien tegen een echt getraind
  tabelregio-model (`table_region_runs/<run>/model.json` +
  `evaluation_artifacts/test_evaluation.json`). Dat heb ik hier niet, en kan
  ik niet nabootsen zonder het risico te lopen een activatiepad te bouwen
  dat er in de code goed uitziet maar in het echte containerpad anders
  gedraagt (andere host-vs-containerpaden, andere Python-omgeving).
- **Toegang tot zo'n omgeving** (jouw kant, of een sessie met
  Docker/GPU-toegang) om de nieuwe subcommand + het herschreven script
  end-to-end te draaien vóór het wordt gecommit.

### Stappen (uit te voeren zodra Docker/GPU-toegang beschikbaar is)
1. De huidige raw-PowerShell-logica (paden-validatie, evaluatie-check,
   `active.json`-formaat) 1-op-1 overzetten naar een nieuwe
   `activate-table-region-model`-subcommand in `cli.py`/`model_registry.py`,
   met dezelfde host-vs-containerpad-vertaling als de bestaande
   `register-localization-model`/`activate-table-cell-model`-subcommands
   al doen.
2. `activate-table-region-model.ps1` herschrijven naar het `docker compose
   --profile training run --rm --build model-manager ...`-patroon van de
   andere drie `activate-*.ps1`-scripts.
3. Tegen een echt getraind tabelregio-model draaien (zowel het oude script
   als het nieuwe, op dezelfde modelmap) en de resulterende `active.json`
   byte-voor-byte vergelijken.
4. Pas als dat gelijk is: committen, en de oude host-pad-validatielogica
   verwijderen.

---

## Samenvatting: wat kan al, wat moet wachten

| Punt | Blokkerende afhankelijkheid | Status |
|---|---|---|
| 1. Frontend review-studio's | — | Nulmeting (stap 1-2) **afgerond**; retry-strategie- en route-beslissing **genomen** (localStorage-queue, `/mapping/<id>`); stap 3-5 kunnen door |
| 2. CLI exit-codes | — | **Afgerond**: audit gedaan, contract gedocumenteerd, 2 subcommands rechtgetrokken |
| 2b. `table_first_cli.py` argv-scanner | — | **Afgerond**: `--name=waarde`-syntax toegevoegd, `--name waarde` bleef werken |
| 3. `activate-table-region-model.ps1` | Docker/GPU-trainingsomgeving | Moet wachten tot die beschikbaar is |
