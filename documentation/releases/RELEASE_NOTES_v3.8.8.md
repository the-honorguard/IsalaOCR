# IsalaOCR 3.8.8 — workflowstappen in plaats van action-ID’s

De interface gebruikt vanaf deze release alleen nog stapnummers voor de functionele workflow. Interne PowerShell/job-ID’s blijven bestaan voor backwards compatibility, maar worden niet meer als gebruikersnummering getoond.

## Workflow

- Stap 1 heet **Voorbereiding** en bevat alle model-, gewicht- en Docker-imagevoorbereiding.
- Pipeline A loopt door van stap 1 t/m 12.
- Mapping & OCR loopt logisch verder van stap 13 t/m 21.
- Field-detector training is één workflowstap; GPU en CPU zijn uitvoeropties binnen die stap.
- Systeemcontroles en Onderhoud zijn beheerpagina’s en hebben geen kunstmatig stapnummer.

## Taken en logs

- Knoppen tonen taaknamen zonder interne action-ID’s.
- Wachtrijbeheer toont geen `Actie 17`-achtige regels meer.
- Worker- en preflightlogs spreken over taken en workflowstappen in plaats van action-nummers.
- De interactieve PowerShell-interface gebruikt dezelfde workflowstappen. Stap 1 heeft een submenu met benoemde voorbereidingstaken.

## Compatibiliteit

De bestaande interne action-ID’s blijven ongewijzigd zodat bestaande scripts, queued jobs en automatisering blijven werken. `TRAINING_IMAGE_VERSION` blijft 3.8.4; zware CPU/GPU training-images worden hierdoor niet opnieuw opgebouwd.
