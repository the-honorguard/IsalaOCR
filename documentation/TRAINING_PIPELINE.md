# IsalaOCR trainingspipeline — v3.14.0

De cropgeometrie wordt table-first opgebouwd. De initiële review is Ground Truth; latere detectorruns worden daartegen vergeleken zonder die Ground Truth opnieuw te overschrijven.

## Pipeline A — Table-first crop geometry

### Stap 1 — Voorbereiding

Controleer de offline inference/runtime en table/cell-modelcache. Stel daarnaast de functionele panelnamen voor het project in.

### Stap 2 — Panelen instellen

De gebruiker bepaalt zelf de zoekgebieden voor bijvoorbeeld LV/RV-resultaatpanelen. De geometrie wordt genormaliseerd opgeslagen zodat dezelfde paneldefinitie op alle bronnen kan worden toegepast.

### Stap 3 — Tabelstructuur detecteren

PP-StructureV3 draait afzonderlijk binnen ieder panel. Meerdere preprocessingvarianten kunnen worden gebenchmarkt. In `table_first` mode worden losse OCR/PicoDet boxes niet in de candidate pool gemengd.

Wanneer in Stap 6 een project-specifiek `RT-DETR-L_wireless_table_cell_det` model is geactiveerd, wordt dat model automatisch gebruikt door de wireless table-cell component van PP-Structure.

Elke complete Stap-3-run wordt vanaf v3.13.3 als afzonderlijke vergelijking-run gearchiveerd. Een mislukte/partiële detectierun wordt niet als geldige vergelijking opgeslagen.

### Stap 4 — Tabelcellen reviewen · initiële Ground Truth

De eerste table-cell review is de canonieke referentie:

- **Correct** — één bruikbare functionele cel;
- **Aangepast** — dezelfde cel, maar de box moest worden gecorrigeerd;
- **Detectiefout** — kandidaat is geen correcte functionele cel;
- **Merged cells** — één machinebox omvat meerdere echte cellen: keur de machinebox af en voeg de afzonderlijke echte cellen toe;
- **Ontbrekende cel** — voeg alleen een echte gemiste functionele cel toe.

Eén kader staat altijd voor één functionele cel.

### Stap 5 — Tabeldekking beoordelen

Meet directe detectorcoverage, geometrische aanpassingen, structurele reconstructies, false candidates en werkelijk handmatig toegevoegde cellen.

### Stap 6 — Tabelmodel verbeteren

De Stap-4 Ground Truth wordt als COCO table-cell dataset vastgelegd. Vervolgens kan `RT-DETR-L_wireless_table_cell_det` worden gefinetuned. Training, validation, registratie en activatie blijven expliciete acties.

De dataset is tevens de **bevroren Ground Truth snapshot** voor Stap 7. Daardoor blijft de referentie stabiel terwijl nieuwe modellen worden getest.

### Stap 7 — Modelvergelijking & vervolg-review

Stap 7 scheidt modelbeoordeling van Ground-Truth-opbouw.

Voor iedere nieuwe Stap-3-run worden predictions rechtstreeks gematcht tegen de bevroren dataset-GT. De standaardvergelijking is de nieuwste run tegen de direct voorafgaande run; de oorspronkelijke Stap-4 machinegeometrie wordt als **Model 0** gereconstrueerd.

De pagina toont onder meer:

- precision, recall en F1;
- direct correct gevonden cellen;
- geometrie-afwijkingen;
- false negatives (gemiste GT-cellen);
- false positives (extra predictions);
- vermoedelijke merged-cell predictions;
- verschil ten opzichte van het vorige model.

Alleen afwijkingen komen in de vervolg-review. Een issue kan als **model fout** worden bevestigd of voor **GT controleren** worden gemarkeerd. Stap 7 wijzigt de Ground Truth niet automatisch. Een echte GT-correctie gebeurt expliciet in Stap 4, waarna een nieuwe dataset in Stap 6 wordt gebouwd.

## Geparkeerde fallback

De oude localization/PicoDet dataset-, training-, evaluatie- en activatieflow blijft beschikbaar, maar is geen onderdeel van de table-first hoofdroute.

## Pipeline B — Mapping & OCR

8. Mapping Studio
9. Mappings toepassen
10. Waarden uitlezen
11. Waarden beoordelen
12. Recognition-dataset bouwen
13. Recognition-dataset valideren
14. Recognition-model trainen
15. Recognition-model evalueren
16. Recognition-model activeren

Recognition leest uitsluitend inhoud binnen reeds bepaalde crops en mag de Ground Truth/cropgeometrie niet impliciet wijzigen.
