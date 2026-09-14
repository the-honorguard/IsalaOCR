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
- [ ] 3. `training/db_generic_detection.py` — `_invalidate_mapped_samples_in_connection`,
      `invalidate_mapped_samples`, `replace_generic_detection`,
      `list_detection_sources`, `get_detection_source`, `list_detected_blocks`,
      `get_detected_block`, `get_detected_relation`
- [ ] 4. `training/db_relation_feedback.py` — `_relation_snapshot_in_connection`,
      `_record_relation_feedback_in_connection`, `record_relation_feedback`,
      `clear_relation_feedback`, `list_relation_feedback`,
      `relation_feedback_stats`, `feedback_for_relations`,
      `list_detected_relations`, `update_relation_contexts`
- [ ] 5. `training/db_mappings.py` — `mapping_counts`, `_mapping_component_in_source`,
      `_upsert_mapping_in_connection`, `upsert_mapping`, `sync_relation_mappings`,
      `get_mapping`, `list_mappings`, `delete_mapping`, `clear_suggested_mappings`,
      `clear_all_mappings`, `save_mapping_profile`, `get_mapping_profile`,
      `list_mapping_profiles`, `update_sample_recognition`
- [ ] 6. `training/db_detection_review.py` — `replace_localization_detection`,
      `list_detection_candidates`, `get_detection_candidate`,
      `list_detection_table_geometry`, `list_detection_table_geometry_by_source`,
      `review_detection_candidate`, `add_detection_annotation`,
      `update_manual_detection_annotation`, `delete_manual_detection_annotation`,
      `accept_unreviewed_detection_candidates`,
      `set_detection_source_review_completed`, `list_detection_annotations`,
      `list_detection_reviews`, `detection_review_counts`,
      `detection_review_counts_by_source`, `detection_table_counts_by_source`
- [ ] 7. `training/db_localization.py` — `save_localization_dataset`,
      `list_localization_datasets`, `save_localization_evaluation`,
      `list_localization_evaluations`, `register_localization_model`,
      `active_localization_model`, `list_localization_models`,
      `get_localization_model`, `get_localization_evaluation`,
      `delete_localization_dataset_record`, `delete_localization_evaluation`,
      `delete_localization_model`
- [ ] 8. `training/db_detection_gate.py` — `set_detection_gate`, `detection_gate`
- [ ] 9. `db.py` blijft: `__init__`, `_file_identity`, `connect`, `_column_names`,
      `_ensure_columns`, `_ensure_review_history_columns`,
      `_ensure_detection_columns`, `_backup_before_migration`,
      `_schema_is_current`, `initialize`, plus de `class TrainingDatabase(
      SamplesMixin, FieldDefinitionsMixin, ...)`-samenstelling

Elke stap: methoden 1-op-1 verplaatsen (geen herschrijving van logica),
benodigde module-level constanten/helpers (bijv. `VALID_STATUSES`, `utc_now`,
`MISSING_MARKERS`) meenemen of importeren, `python -m pyflakes` + volledige
testsuite draaien, dan pas committen/pushen.

## webui.py dispatcher-opsplitsing (na de db.py-stappen)

- [ ] 10. Inventariseer de exacte `step_key ==`-takken in `/process/<step_key>`
       (webui.py) en hun benodigde closures per tak.
- [ ] 11+. Eén tak per stap omzetten naar een losse, benoemde functie
       (`_process_step_<key>(...)`) met expliciete parameters, aangeroepen
       vanuit de (dan veel kortere) dispatcher. Geen gedragswijziging.
- [ ] Laatste stap: evalueren of (een deel van) deze functies alsnog naar een
       eigen module kunnen verhuizen zonder circulaire import met de
       `routes_*.py`-bestanden die ze nu al aanroepen.

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
