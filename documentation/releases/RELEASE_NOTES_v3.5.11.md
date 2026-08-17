# IsalaOCR v3.5.11

## Procesgerichte webinterface

- De volledige OCR-trainingsworkflow is opgesplitst in dertien afzonderlijke processtappen.
- Iedere stap heeft een eigen navigatietab met alleen de vereisten, acties, status en resultaten die voor die stap relevant zijn.
- Het workflow-overzicht verwijst rechtstreeks naar iedere afzonderlijke stap.
- Bestaande detailpagina's voor DICOM-viewing, ROI-beoordeling en waardenreview blijven beschikbaar vanuit de bijbehorende stap.

## Altijd zichtbare taakuitvoer

- Een aangemaakte taak toont onmiddellijk een tijdstempel, taaknaam, taak-ID en wachtrijstatus.
- De PowerShell-worker schrijft eigen levenscyclusregels naar een afzonderlijk workerlog.
- De terminal combineert taakstatus, workerlog, PowerShell/Docker-uitvoer en STDERR.
- Lege of NUL-gevulde Windows-logbestanden worden correct gedecodeerd in plaats van als een leeg zwart vlak weergegeven.
- Statische CSS- en JavaScriptbestanden krijgen een versiesleutel, zodat een browser na een update geen oude interfacecode blijft gebruiken.
