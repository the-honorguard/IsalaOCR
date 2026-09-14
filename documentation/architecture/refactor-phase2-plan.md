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
- [ ] `webui.py:918,939,969,1042,1068,1089` (6 plekken)
- [ ] `recognition_ground_truth_web.py:29,53,74,101,161,207` (6 plekken)
- [ ] `recognition_ground_truth.py:304,438,444`
- [ ] `routes_roi_review.py:35`
- [ ] `routes_value_review.py:133`
- [ ] `mapping.py:1004,1017`
- [ ] `dataset.py:124`
- [ ] `labeler.py:56`
- [ ] `table_cell_training.py:92`
- [ ] `table_model_comparison.py:655`

## Status per item

- [ ] 1. Raw-SQL-plekken (zie inventaris hierboven — deels afgerond)
- [ ] 2. Geometrie/IoU-module
- [ ] 3. FieldSpec.whitelist-onderzoek
- [ ] 4. `_similarity`-functies
- [ ] 5. CLI-duplicatie
- [ ] 6. PowerShell-scripts
- [ ] 7. JSON-foutrespons-helper
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
