# Start here — IsalaOCR 3.14.0

Run `START.cmd`. De lokale webinterface is de primaire bediening.

## 1. Selecteer eerst een project

De projectselector in de sidebar bepaalt de context voor reviewdata, mappings, datasets, modellen, evaluaties en output. Gedeelde Paddle/PaddleX-caches en Docker-infrastructuur blijven globaal.

## 2. Pipeline A — Table-first crop geometry

De hoofdflow gebruikt table-first geometrie; de oude losse PicoDet field detector blijft geparkeerd als fallback.

1. **Voorbereiding** — controleer inference OCR + PP-Structure/table-cell modellen en stel de functionele panelnamen in.
2. **Panelen instellen** — teken de projectbrede zoekgebieden voor de relevante resultaatpanelen.
3. **Tabelstructuur detecteren** — voer PP-StructureV3 per panel uit. Wanneer een project-specifiek wireless table-cell model actief is, gebruikt Stap 3 dat model automatisch.
4. **Tabelcellen reviewen** — dit is de initiële ground-truthfase. Eén kader = één functionele cel. Corrigeer boxes, keur detectiefouten af en voeg gemiste cellen toe.
5. **Tabeldekking beoordelen** — meet directe coverage, correcties, reconstructies en echte handmatige fallback.
6. **Tabelmodel verbeteren** — bouw een COCO dataset uit Stap 4, fine-tune `RT-DETR-L_wireless_table_cell_det`, valideer en activeer het model expliciet.
7. **Modelvergelijking & vervolg-review** — voer na activatie Stap 3 opnieuw uit en vergelijk de nieuwe run met de bevroren Stap-4 Ground Truth en het vorige model. Alleen FN/FP, geometrie-afwijkingen en merged-cell gevallen komen in de vervolg-review.

Stap 7 verandert de Ground Truth nooit automatisch. Als de GT zelf onjuist blijkt, open je de betreffende bron in Stap 4, corrigeer je die bewust en bouw je daarna een nieuwe dataset in Stap 6.

## 3. Pipeline B — Mapping & OCR

Pipeline B blijft afhankelijk van de table-first geometriepoort.

8. **Mapping Studio** — koppel semantische velden aan betrouwbare cell-geometrie.
9. **Mappings toepassen** — materialiseer de definitieve functionele crops.
10. **Waarden uitlezen** — voer recognition alleen op die crops uit.
11. **Waarden beoordelen** — beoordeel OCR-inhoud, niet de cropgeometrie.
12. **Recognition-dataset bouwen**.
13. **Recognition-dataset valideren**.
14. **Recognition-model trainen**.
15. **Recognition-model evalueren**.
16. **Recognition-model activeren**.

Onder **System** blijft **Data & modellen** ongenummerd. Bestaande fallback/localization artifacts worden door de table-first flow niet verwijderd.
