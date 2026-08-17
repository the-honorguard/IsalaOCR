# IsalaOCR 3.13.1

## Persistent canonical Ground Truth

Na de eerste table-cell trainingsdataset wordt de oorspronkelijke Stap-4 review vastgelegd als `table_cell_ground_truth.json`. Stap 4 opent daarna altijd deze canonieke GT en mengt geen nieuwe Stap-3 predictions meer in de reviewer.

Je kunt GT-cellen rechtstreeks verwijderen, aanpassen of toevoegen. Elke wijziging verandert de GT-revisie en maakt de bestaande trainingsdataset zichtbaar verouderd. Stap 6 bouwt vervolgens een nieuwe dataset uit deze GT en kan het table-cell model opnieuw trainen.

Stap 7 blijft run-aware en is de enige plek voor vergelijking van het vorige en nieuwe detector-model.
