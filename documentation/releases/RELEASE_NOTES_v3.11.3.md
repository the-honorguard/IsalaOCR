# IsalaOCR 3.11.3

## Panel Setup voor table-first detectie

- Nieuwe expliciete Stap 2: **Panelen instellen**. De gebruiker bepaalt zelf welke resultaatpanelen door PP-Structure worden geanalyseerd.
- Panelen worden projectbreed als genormaliseerde coördinaten opgeslagen en daardoor over resoluties heen hergebruikt.
- Een eerste full-image voorbeeldscan kan bronrenders en Paddle-regiosuggesties genereren wanneer nog geen preview bestaat.
- Automatische panel-focus is niet langer leidend; Paddle-regio's zijn alleen suggesties/snapdoelen.
- Preprocessing-benchmark draait per opgeslagen panel en kiest per panel onafhankelijk de beste variant.
- Resultaten van meerdere panelen worden teruggeprojecteerd naar de volledige bronafbeelding en samengevoegd.
- Een gewijzigd panelprofiel maakt bestaande table-detectie expliciet verouderd; review en quality-gate vereisen daarna een nieuwe Stap-3 run.
- Panel Setup bevat tekenen, benoemen, verwijderen, Paddle-suggesties overnemen en **Snap naar Paddle-regio**.
- Hoofdworkflow is nu: Voorbereiding → Panelen instellen → Tabelstructuur detecteren → Tabelcellen reviewen → Tabeldekking beoordelen → Mapping.
