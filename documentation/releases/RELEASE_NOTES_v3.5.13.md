# IsalaOCR v3.5.13

## Strikte scheiding tussen ROI- en waardenbeoordeling

- **ROI beoordelen** toont uitsluitend de bronafbeelding, ROI-kaders, crops, coördinaten en technische detectiegegevens.
- OCR-uitvoer, OCR-confidence, exacte labels en waardestatussen zijn uit de ROI-schermen verwijderd.
- **Waarden beoordelen** toont uitsluitend de crop, modeluitvoer, OCR-confidence, exacte tekst en inhoudelijke waardebeslissing.
- Locatorgegevens, extractiemethode, ROI-coördinaten en de actie `ROI/extractie fout` zijn uit de waardenschermen verwijderd.
- Alleen ROI's die in stap 3 definitief als correct zijn opgeslagen, komen beschikbaar in stap 4.
- De keuze **Later** heeft een eigen status en blijft bij opnieuw openen behouden; nieuwe onbeoordeelde ROI's blijven standaard op OK staan.

## Workflow- en dataconsistentie

- Een ROI die naar `fout` of `later` wordt gezet, maakt een bestaande waardebeoordeling ongeldig en bewaart de oude beslissing in de reviewhistorie.
- Gewijzigde crops of detectiemethoden zetten zowel de ROI- als waardebeoordeling terug naar openstaand.
- Datasetbouw gebruikt uitsluitend goedgekeurde waarden waarvan de ROI definitief correct is.
- Oude waardestatussen `roi_error` worden bij migratie verplaatst naar de afzonderlijke ROI-status `incorrect`.
- Detectieschermen tonen alleen technische detectie-informatie en geen waardebeoordelingen meer.
