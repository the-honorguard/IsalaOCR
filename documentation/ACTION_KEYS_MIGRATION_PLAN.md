# Plan: van numerieke action-ID's naar betekenisvolle action keys

## Doel

Vervang de door de hele applicatie verspreide numerieke actie-ID's (`"2"`,
`"62"`, enzovoort) door stabiele, leesbare action keys zoals
`collect_training_data` en `run_detection_lab`.

Dit wordt een harde overgang. Er is geen compatibiliteitslaag voor oude
queue-items nodig, omdat er volgens de huidige operationele afspraak geen oude
jobs hoeven te worden behouden.

## Gewenste eindtoestand

Er is één centrale catalogus met per actie:

- `key`: de technische identifier, bijvoorbeeld `run_detection_lab`;
- `name`: de zichtbare Nederlandse naam;
- `script`: het PowerShell-script, indien van toepassing;
- `profile`: het vereiste Docker/worker-profiel;
- optioneel: duration, categorie, requirements en parameters.

Alle interne code gebruikt de key. Een job-payload bevat bijvoorbeeld:

```json
{
  "action_key": "run_detection_lab",
  "action_name": "Detectie-lab: 3 celdetectie-aanpakken vergelijken",
  "options": {"source_id": "..."}
}
```

De key is stabiel en mag niet veranderen omdat de zichtbare naam verandert.
Nummering wordt nergens meer gebruikt voor dispatch, validatie, gating,
filtering of UI-koppeling.

## Voorgestelde action keys

De definitieve lijst moet uit de actuele `ACTIONS`-catalogus worden afgeleid.
Gebruik deze naamgevingsregels:

- werkwoord + object: `collect_training_data`, `train_table_model`;
- expliciete varianten: `train_recognition_model_gpu`;
- vergelijkingen: `compare_recognition_models`, `run_detection_lab`;
- systeemacties: `check_docker`, `prepare_inference_models`;
- legacy/fallback blijft in de key herkenbaar: `evaluate_legacy_detector`.

Maak vóór de codewijziging een volledige mapping-tabel van elke bestaande
actie naar precies één nieuwe key. Geen nummers overslaan of hergebruiken.

## Uitvoeringsvolgorde

### 1. Catalogus centraliseren

1. Maak een klein Python-modulebestand voor de action catalogus, bijvoorbeeld
   `application/src/isala_ocr/action_catalog.py`.
2. Definieer daar een immutable catalogus en helpers:
   `get_action(key)`, `action_keys()`, `action_name(key)` en
   `actions_for_step(step_key)`.
3. Verplaats de huidige `ACTIONS`, duration-estimates en relevante metadata
   uit `training/webui.py` naar deze catalogus.
4. Laat preflight en tests uitsluitend deze catalogus als bron gebruiken.

### 2. Queue-contract wijzigen

1. Vervang `action_id` door `action_key` in enqueue-, status-, retry- en
   artifact-jobcode.
2. Hernoem lokale variabelen, functies en JSON-velden consequent.
3. Laat ontbrekende of onbekende keys direct een duidelijke fout geven.
4. Verwijder bestaande pending/running/status-jobbestanden vóór de nieuwe
   versie wordt gestart, na een read-only inventarisatie. Alleen de expliciet
   afgesproken oude jobs mogen worden verwijderd.
5. Pas jobfilters, activity-dock polling, jobdetails en retry aan.

### 3. Worker en PowerShell-laag

1. Laat `webui-worker.ps1` dispatchen op `action_key`.
2. Laat `launcher.ps1`, `training-menu.ps1`, `preflight.ps1` en alle
   action-scripts keys ontvangen.
3. Hernoem parameters zoals `ActionId` naar `ActionKey`.
4. Vervang numerieke sets in conditionals door named sets, bijvoorbeeld
   `@("run_detection_lab", "collect_training_data")`.
5. Log zowel de key als de zichtbare naam.
6. Herstart de langlopende worker na installatie; een bestandwijziging alleen
   laadt PowerShell-code die al in geheugen zit niet opnieuw.

### 4. WebUI, routes en JavaScript

1. Vervang hidden inputs, fetch-payloads en routevalidatie door `action_key`.
2. Pas `routes_jobs.py`, localization-routes, detection-lab-routes en alle
   formulieren aan.
3. Vervang `action_ids` in `PROCESS_STEPS` door `action_keys`.
4. Pas `job-runtime.js`, activity-dock filters en browser selectors aan.
5. Controleer dat zichtbare labels niet als technische identifier worden
   gebruikt.

### 5. Preflight, voorbereiding en documentatie

1. Laat preflight acties op key valideren en toon keys alleen waar dat voor
   diagnose nuttig is.
2. Pas preparation-status en alle `full_action_id`, `download_action_id`,
   `install_action_id` en `check_action_id`-velden aan naar `*_action_key`.
3. Zoek daarna opnieuw repository-breed naar numerieke action-ID patronen.
4. Werk README's, architectuurdocumentatie, changelog en testfixtures bij.

### 6. Tests en verificatie

Voeg eerst contracttests toe voor:

- unieke keys en unieke catalogusentries;
- elke catalogusactie heeft een geldig script/profile;
- elke workflowstap verwijst alleen naar bestaande keys;
- enqueue schrijft `action_key` en geen `action_id`;
- worker-dispatch kiest het juiste script voor elke key;
- options zoals `source_id`, `device` en `start_from` blijven behouden;
- retry behoudt de action key en options;
- onbekende of numerieke keys worden geweigerd;
- JavaScript polling/filtering gebruikt de key.

Voer daarna uit:

1. Python compile/syntaxchecks;
2. volledige relevante pytest-suite in de projectruntime/container (lokaal
   Windows mag ontbreken­de `cv2` expliciet als omgevingsblokkade rapporteren);
3. PowerShell parsechecks;
4. preflight;
5. een queue-smoke met `run_detection_lab` en een gecontroleerde
   `source_id`;
6. browsercontrole: actie starten, jobstatus volgen, foutlog bekijken en
   resultaatpagina openen;
7. worker restart en een tweede smoke om stale-processgedrag uit te sluiten.

## Acceptatiecriteria

- `rg` vindt geen productiegebruik meer van `action_id`, numerieke action sets
  of numerieke hidden action values.
- Eén catalogus is de enige bron voor actie-key, naam, script en profile.
- Een nieuwe Detectie-lab-job bevat `action_key: run_detection_lab` en geeft
  de gekozen `source_id` door tot aan het PowerShell-script.
- Retry, cancel, status, activity dock en foutlogging werken op keys.
- Alle relevante tests en preflight zijn groen; ontbrekende lokale dependencies
  zijn apart benoemd.
- De worker is na de overgang aantoonbaar opnieuw gestart.
- De wijziging wordt als één gerichte migratie gemerged; half oude/half nieuwe
  queuecontracten zijn niet toegestaan.

## Risico's en beslissingen

- **Oude jobs:** harde overgang is toegestaan, maar inventariseer en ruim de
  queue expliciet op voordat de nieuwe worker wordt gestart.
- **Externe scripts:** zoek naar aanroepen buiten deze repository voordat
  parameters worden hernoemd.
- **Cache/runtime:** rebuild images én herstart langlopende workers; anders kan
  oude dispatchcode actief blijven.
- **Numerieke verwijzingen in historische documentatie:** mogen blijven als
  historische context, maar niet in uitvoerbare code, actuele instructies of
  tests.
- **Branching:** werk op een aparte branch, voer de contract- en smokechecks
  uit, merge daarna naar `main` en controleer de schone werkboom.

