# IsalaOCR 3.13.4

## Stap 7 — prediction direct aan Ground Truth toevoegen

Bij een `Extra detectie (FP)` die in werkelijkheid een echte tabelcel is, kan de reviewer nu direct **+ Toevoegen aan GT** kiezen. Het exacte prediction-kader wordt server-side naar volledige broncoördinaten omgerekend en toegevoegd aan de persistente canonieke Ground Truth.

De actie is idempotent: herhaald klikken maakt geen duplicate GT-cel. Na toevoegen wordt de huidige table-cell trainingsdataset als verouderd beschouwd; bouw Stap 6 opnieuw voordat je verder traint. Verwijderen of geometrie aanpassen blijft een expliciete Stap-4-actie.
