# db.py / webui.py opsplitsing — uitvoeringsplan

Status: wordt automatisch bijgewerkt terwijl dit stap voor stap wordt uitgevoerd
(zie `documentation/CODE_REVIEW_v3.16.0.md`, sectie "Hoog", voor de oorspronkelijke
bevindingen). Elke stap is een eigen commit op `claude/code-review-calls-jc8xyn`
(PR #38), alleen gepusht nadat de volledige testsuite groen is (op de 6
vooraf-bestaande, onafhankelijke falende tests na).

## Aanpak

**`db.py` (3076 regels, 94 methoden op `TrainingDatabase`)**: opgesplitst via
mixin-classes. `TrainingDatabase` blijft precies dezelfde publieke interface
houden (`TrainingDatabase(path).any_method(...)` blijft overal werken) — alleen
de methode-*implementaties* verhuizen naar aparte, per-onderwerp bestanden die
elk een mixin-class definiëren. `TrainingDatabase` erft van alle mixins plus de
schema/connectie-kern die in `db.py` blijft staan. Dit is een mechanische
verplaatsing zonder gedragswijziging: alle mixin-methoden werken nog via
`self` op dezelfde instantie, dus methoden die elkaar aanroepen over
mixin-grenzen heen blijven gewoon werken.

**`webui.py` (4079 regels)**: eerst de `/process/<step_key>`-dispatcher
(~980 regels, 18+ `elif`-takken) opsplitsen in losse, benoemde functies
binnen hetzelfde bestand (elke tak krijgt de closures die hij nodig heeft
expliciet als parameter) — dat verkleint de functie zelf drastisch zonder de
closure-deel-problematiek aan te raken die de oorspronkelijke `routes_*.py`-
opsplitsing al tegenhield. Pas daarna, per tak, beoordelen of verplaatsing
naar een eigen bestand (net als `routes_*.py`) haalbaar is zonder circulaire
imports.

## db.py mixin-opsplitsing (volgorde van uitvoering)

- [x] 0. `training/db_constants.py` — verplaats `SCHEMA_VERSION`, alle `VALID_*`-sets,
      `MISSING_MARKERS`, `utc_now()` en `validate_exact_label()` hierheen.
      `db.py` blijft ze re-exporteren (`from .db_constants import *` of expliciet)
      zodat alle bestaande `from .db import utc_now` / `from isala_ocr.training.db
      import SCHEMA_VERSION` e.d. elders in de codebase blijven werken. Reden:
      zonder dit zouden de mixins hieronder circulair van `.db` moeten
      importeren terwijl `db.py` zelf die mixins importeert.
- [x] 1. `training/db_samples.py` — `_invalidates_review`, `upsert_sample`, `get`,
      `review`, `review_header`, `header_review_counts`, `list_header_samples`,
      `header_training_rows`, `review_roi`, `list_samples`, `accepted`,
      `counts`, `mapped_sample_counts`
- [x] 2. `training/db_field_definitions.py` — `fields`, `_safe_field_key`,
      `seed_field_definitions`, `upsert_field_definition`, `set_field_active`,
      `get_field_definition`, `list_field_definitions`
- [x] 3. `training/db_generic_detection.py` — `_invalidate_mapped_samples_in_connection`,
      `invalidate_mapped_samples`, `replace_generic_detection`,
      `list_detection_sources`, `get_detection_source`, `list_detected_blocks`,
      `get_detected_block`, `get_detected_relation`
- [x] 4. `training/db_relation_feedback.py` — `_relation_snapshot_in_connection`,
      `_record_relation_feedback_in_connection`, `record_relation_feedback`,
      `clear_relation_feedback`, `list_relation_feedback`,
      `relation_feedback_stats`, `feedback_for_relations`,
      `list_detected_relations`, `update_relation_contexts`
- [x] 5. `training/db_mappings.py` — `mapping_counts`, `_mapping_component_in_source`,
      `_upsert_mapping_in_connection`, `upsert_mapping`, `sync_relation_mappings`,
      `get_mapping`, `list_mappings`, `delete_mapping`, `clear_suggested_mappings`,
      `clear_all_mappings`, `save_mapping_profile`, `get_mapping_profile`,
      `list_mapping_profiles`, `update_sample_recognition`
- [x] 6. `training/db_detection_review.py` — `replace_localization_detection`,
      `list_detection_candidates`, `get_detection_candidate`,
      `list_detection_table_geometry`, `list_detection_table_geometry_by_source`,
      `review_detection_candidate`, `add_detection_annotation`,
      `update_manual_detection_annotation`, `delete_manual_detection_annotation`,
      `accept_unreviewed_detection_candidates`,
      `set_detection_source_review_completed`, `list_detection_annotations`,
      `list_detection_reviews`, `detection_review_counts`,
      `detection_review_counts_by_source`, `detection_table_counts_by_source`
- [x] 7. `training/db_localization.py` — `save_localization_dataset`,
      `list_localization_datasets`, `save_localization_evaluation`,
      `list_localization_evaluations`, `register_localization_model`,
      `active_localization_model`, `list_localization_models`,
      `get_localization_model`, `get_localization_evaluation`,
      `delete_localization_dataset_record`, `delete_localization_evaluation`,
      `delete_localization_model`
- [x] 8. `training/db_detection_gate.py` — `set_detection_gate`, `detection_gate`
- [x] 9. `db.py` blijft: `__init__`, `_file_identity`, `connect`, `_column_names`,
      `_ensure_columns`, `_ensure_review_history_columns`,
      `_ensure_detection_columns`, `_backup_before_migration`,
      `_schema_is_current`, `initialize`, plus de `class TrainingDatabase(
      SamplesMixin, FieldDefinitionsMixin, ...)`-samenstelling

**db.py-opsplitsing afgerond en geverifieerd (2026-09-14):** `db.py` ging van
3076 naar 656 regels (schema/connectie-kern + de acht mixin-imports en de
`TrainingDatabase`-klassesamenstelling). Methode-voor-methode vergelijking
tussen de oorspronkelijke `TrainingDatabase` (commit `bcb2f1d`) en de huidige
klasse via introspectie (`dir(TrainingDatabase)`) bevestigt: exact dezelfde
90 methoden, niets kwijtgeraakt of per ongeluk gedupliceerd.
`python -m pyflakes application/src/isala_ocr` is schoon op de bewuste
`db_constants`-re-exports en de eerdere `passes_detection_gate`-re-export na;
volledige testsuite exact op de 6 bekende, onafhankelijke faalpunten.

Elke stap: methoden 1-op-1 verplaatsen (geen herschrijving van logica),
benodigde module-level constanten/helpers (bijv. `VALID_STATUSES`, `utc_now`,
`MISSING_MARKERS`) meenemen of importeren, `python -m pyflakes` + volledige
testsuite draaien, dan pas committen/pushen.

## webui.py dispatcher-opsplitsing (na de db.py-stappen)

- [x] 10. Inventariseer de exacte `step_key ==`-takken in `/process/<step_key>`
       (webui.py) en hun benodigde closures per tak.

**Inventaris `process_step()` (webui.py, huidige regels ~2958-3815):**

De functie heeft geen uniforme structuur; het is een opeenvolging van vroege
returns, een apart POST-blok, en daarna een GET-renderblok, met aan het eind
één gedeelde `render_template("process_step.html", ...)`-fallback.

*Vroege returns/redirects (2960-2976):*
- `legacy_step_aliases`-redirect (localization-validate/-train/-compare → nieuwe keys)
- `value-extract` GET → redirect naar `apply-mapping`
- `detection-review` GET → redirect naar `detection_review_index`

*Zelfstandige branch (2977-3024):* `input-selection` (GET+POST, inputbestanden
selecteren, optioneel bronpreview starten) — retourneert altijd zelf, gebruikt
`input_selection_state`, `input_selection_path`, `selection_payload`,
`prepare_source_renders`, `_record_webui_error`.

*Gedeelde queryparam-validatie (3025-3033):* `header_status`/`source_id`/
`sample_id`/`extraction_method` — wordt alleen echt gebruikt door de
POST-afhandeling van `header-normalization` (zie hieronder); geen GET-render
voor die stap is in deze functie gevonden (mogelijk legacy/dood pad, nader te
onderzoeken bij extractie).

*POST-only blok (`if request.method == "POST":`, 3034-3373), één return/redirect per tak:*
- `table-quality` (3035-3067): tabelrollen/-rijen opslaan + recognition-scope opslaan
- `table-compare` (3068-3257): comparison-review-acties (issue beoordelen, functionele/model-fout-suggesties toepassen)
- `localization-dataset` (3258-3294): dataset-split opslaan (auto of handmatig)
- impliciete `header-normalization`-fallback (3295-3373): rijheader-reviews opslaan, optioneel normalisatiemodel trainen + redetect-job starten; alle andere step_keys krijgen hier `abort(405)`

*GET-renderblok (3375-3805), één `return render_template(...)` per tak:*
- `panel-setup` (3375-3400): tabelpanelen-overzicht
- `table-region-model` (3402-3424): tabelregio-trainingsstatus
- `table-quality` (3426-3614): grote inline rij/kolom-clusteringlogica (`indexed_cells`, `axis_groups`, `table_record` als geneste helperfuncties) + twee losse templates afhankelijk van `?view=geometry`
- `table-model` (3616-3659): table-cell-trainingsstatus/gereedheid
- `table-compare` (3661-3678): vergelijkingsresultaten tussen modelruns
- `localization-dataset` (3680-3681): rendert enkel de React-workbench-template
- `{localization-evaluate, localization-register, detection-report}` (3683-3684): rendert enkel de React-quality-template
- `detect-candidates` + `table_first`-strategie (3689-3718): tabelregio-review-oppervlak (apart van Panel Setup, expliciet om verwarring met regio-GT te voorkomen)
- `artifacts` (3720-3721): hergebruikt `render_management(active_tab="models")`
- generieke staat-opbouw + `elif`-keten (3730-3805) die alleen `state`/`header_counts` vult vóór de gedeelde template-call:
  `detection-models`, `{detect-candidates, detection-review}` (met geneste table_first-tak), `redetect`, `mapping`, `{apply-mapping, value-extract}`, `value-review`, `recognition-*` (prefix-match), fallback `step.get("group") == "value"`
- gedeelde afsluitende `render_template("process_step.html", ...)` (3806-3815) met per-stap ternaire label-expressies

**Consequentie voor stap 11+:** dit is geen simpele "elke tak is een losse,
onafhankelijke functie"-extractie — de POST- en GET-kant van dezelfde
`step_key` (bijv. `table-quality`, `table-compare`, `localization-dataset`)
staan ver uit elkaar en horen inhoudelijk bij elkaar; de grote inline
helperfuncties in de `table-quality`-GET-tak (`indexed_cells`, `axis_groups`,
`table_record`) sluiten over lokale variabelen (`profile`, `semantic_assignments`,
`studio_source_id`) die niet zomaar los te trekken zijn zonder ook die mee te
verplaatsen. Aanpak: per `step_key` (niet per losse `if`-tak) een
`_process_step_<key>(...)`-functie maken die zowel de POST- als de
GET-afhandeling voor die stap bevat, met de benodigde closures/`database`/
`workspace_root` etc. als parameters; de hoofdfunctie wordt dan een korte
lookup-dispatch (`handler = _STEP_HANDLERS.get(step_key)`) in plaats van een
lange `if`/`elif`-keten.
- [x] 11a. `input-selection` (GET+POST) verplaatst naar een losse geneste
       functie `_process_step_input_selection(step)`, aangeroepen vanuit
       `process_step()`. Nog steeds een closure over `create_web_app()`'s
       locals (nog geen expliciete parameters voor alle closures) - dat komt
       pas aan bod bij de laatste stap hieronder, waar wordt beoordeeld of
       verplaatsing naar een eigen bestand haalbaar is.
- [x] 11b. De `elif`-keten die alleen `state`/`header_counts` vulde
       (`detection-models`, `{detect-candidates, detection-review}`,
       `redetect`, `mapping`, `{apply-mapping, value-extract}`,
       `value-review`, `recognition-*`-prefix) omgezet naar acht losse
       `_process_step_state_<naam>()`-functies plus een
       `_PROCESS_STEP_STATE_BUILDERS`-dispatch-dict; `process_step()` doet nu
       een lookup in plaats van de lange keten. `process_step()` zelf ging
       van ~980 naar 746 regels.
       Let op tijdens deze stap: `tests/test_preparation_readiness_v3111.py`
       controleerde de letterlijke broncode-string
       `state["preparation"] = preparation_for_current_strategy()` - een
       dict-literal-vorm brak die test zonder gedragsverschil; teruggezet
       naar de exacte toewijzingsvorm zodat de test ongewijzigd kon blijven.
- [x] 11c. De kleinere zelfstandige GET-renderfuncties verplaatst naar losse
       geneste functies (zelfde patroon als 11a): `panel-setup` →
       `_process_step_panel_setup(step)`, `table-region-model` →
       `_process_step_table_region_model(step)`, `table-model` →
       `_process_step_table_model(step)`, `table-compare` (GET) →
       `_process_step_table_compare_get(step)`, `detect-candidates`+
       table_first → `_process_step_detect_candidates_table_first(step)`.
       `localization-dataset` (GET), `{localization-evaluate,
       localization-register, detection-report}` (GET) en `artifacts` bleven
       bewust inline: elk is al maar 1-2 regels, een aparte functie zou daar
       alleen ceremonie toevoegen zonder de dispatcher echt te verkleinen.
       `process_step()`: 746 → 615 regels.
- [x] 11d. De vier resterende POST-takken verplaatst naar losse geneste
       functies: `table-quality` POST → `_process_step_table_quality_post(step_key)`,
       `table-compare` POST (5 sub-acties: review_issue, add_prediction_to_gt,
       apply_functional_suggestions, apply_model_error_suggestions,
       apply_all_open_geometry_functional_ok) → `_process_step_table_compare_post(step_key)`,
       `localization-dataset` POST → `_process_step_localization_dataset_post(step_key)`,
       impliciete `header-normalization`-POST-fallback →
       `_process_step_header_normalization_post(step_key, header_status_filter,
       header_source_filter, header_sample_filter, header_method_filter)` (deze
       laatste kreeg de vier filter-locals expliciet als parameter, omdat die
       -- anders dan `header_profile` -- lokaal in `process_step()` berekend
       worden en dus geen closure-var van `create_web_app()` zijn). De
       `if request.method == "POST":`-tak in `process_step()` is nu een kale
       4-weg dispatch van één regel per tak. `process_step()`: 615 → 352
       regels.
- [ ] 11e. Laatste en grootste resterende tak: de `table-quality` GET-tak
       (~190 regels, met geneste `indexed_cells`/`axis_groups`/
       `table_record`-helperfuncties die closen over locals als `profile`,
       `semantic_assignments`, `studio_source_id`) verplaatsen naar
       `_process_step_table_quality_get(step)` volgens hetzelfde patroon. Dit
       is bewust als laatste stap bewaard: de geneste helpers maken deze tak
       complexer om foutloos te knippen dan de andere.
- [ ] Laatste stap: evalueren of (een deel van) deze functies alsnog naar een
       eigen module kunnen verhuizen zonder circulaire import met de
       `routes_*.py`-bestanden die ze nu al aanroepen (daarvoor moeten hun
       closures alsnog expliciete parameters worden).

## Validatie per stap

1. `python -m pyflakes application/src/isala_ocr` (geen nieuwe ongebruikte
   imports/namen).
2. `python -m pytest tests -q` vanuit de repo-root — moet exact op de 6
   bekende, onafhankelijke faalpunten uitkomen (nooit meer).
3. Alleen dan committen en pushen naar `claude/code-review-calls-jc8xyn`.

Als een stap niet zonder twijfel veilig kan (bijv. een methode-aanroep die
buiten de mixin-grens niet vanzelfsprekend blijft werken, of een testfalen dat
niet aan een van de 6 bekende oorzaken te wijten is): stoppen, de reden hier
noteren, en niet doorgaan zonder menselijke beoordeling.
