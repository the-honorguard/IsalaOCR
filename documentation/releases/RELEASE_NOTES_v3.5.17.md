# IsalaOCR 3.5.17

## Ruwe rijheader-OCR zichtbaar

In **Stap 3 · Rijheaders trainen** wordt nu expliciet onderscheid gemaakt tussen:

- **Ruwe OCR-uitvoer · zonder normalisatie**: de tekst uit de geselecteerde OCR-tokens, met oorspronkelijke hoofdletters en tekens;
- **Genormaliseerd voor vergelijking**: de interne vereenvoudigde zoekvorm die voor fuzzy matching wordt gebruikt;
- **Huidige koppeling**: het functionele veld waaraan de rijheader is gekoppeld.

De eerdere aanduiding **Detectie-confidence** is vervangen door **Locator-matchscore**, omdat deze score de kwaliteit van de veldmatch weergeeft en niet uitsluitend de OCR-zekerheid.

Bestaande detecties hoeven niet opnieuw uitgevoerd te worden: `locator_label_text` bevatte de ruwe OCR-tokenuitvoer al. Deze versie maakt dat verschil zichtbaar in de interface.
