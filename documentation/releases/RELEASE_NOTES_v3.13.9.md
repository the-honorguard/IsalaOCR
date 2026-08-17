# IsalaOCR 3.13.9

## Stap 7: containment recovery voor oversized predictions

Stap 7 gebruikte tot nu toe IoU ≥ 50% als minimale koppeling tussen een nieuwe prediction en de canonieke Ground Truth. Een prediction die de volledige juiste cel omvatte maar veel ruimer was, kon daardoor als twee losse fouten verschijnen: één `Extra detectie (FP)` en één `GT-cel gemist (FN)`.

Vanaf 3.13.9 krijgt zo'n prediction een tweede matchkans. Wanneer de prediction minstens 95% van precies één nog niet gekoppelde GT-cel afdekt, worden prediction en GT gekoppeld als één `Geometrie afwijkend`-item. Stap 7 toont daarbij de bestaande GT-dekking en extra-prediction-metrics en biedt `Functioneel correct ✓`, `Model fout ✓` en `GT controleren`.

De fallback is bewust niet van toepassing wanneer dezelfde prediction meerdere GT-cellen substantieel afdekt. Zulke gevallen blijven als merged-cell-probleem zichtbaar.

Bestaande schema-v1 vergelijkingsruns worden tijdens het openen opnieuw geëvalueerd vanuit hun opgeslagen predictions en bevroren GT. De oorspronkelijke runbestanden worden niet gewijzigd en een nieuwe detectierun is niet nodig.
