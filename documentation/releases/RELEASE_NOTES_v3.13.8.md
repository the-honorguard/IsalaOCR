# IsalaOCR 3.13.8

## Stap 7 · functioneel correcte geometrie

Stap 7 maakt nu onderscheid tussen een echte modelmisser en een geometrische afwijking die downstream nog volledig bruikbaar is.

- Nieuwe reviewbeslissing **Functioneel correct ✓** voor uitsluitend `Geometrie afwijkend`.
- De canonieke Ground Truth blijft ongewijzigd; een ruimer prediction-kader wordt dus niet teruggeschreven naar GT.
- Een functioneel-correct oordeel wordt apart als `functional_ok` opgeslagen en niet als `model_error`.
- Geometrie toont naast IoU ook **GT gedekt** en **extra prediction**.
- Een niet-bindende hint **waarschijnlijk bruikbaar** verschijnt bij minimaal 95% GT-dekking en maximaal 30% prediction-oppervlak buiten de GT.
- De hint keurt niets automatisch goed; de reviewer blijft bepalen of extra beeldinhoud functioneel onschadelijk is.
- Bestaande, reeds opgeslagen Stap-7-runs krijgen de nieuwe geometriekenmerken tijdens het tonen berekend en hoeven niet opnieuw gedetecteerd te worden.
- `functional_ok` wordt server-side geweigerd voor FP, FN en merged-cell issues.
