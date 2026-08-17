# IsalaOCR 3.13.0

## Modelvergelijking & vervolg-review

Deze release voegt een aparte **Stap 7** toe voor iteratieve table-cell modelverbetering.

- Stap 4 blijft de initiële Ground Truth-review.
- Stap 6 bouwt/trained het project-specifieke wireless table-cell model.
- Na activatie wordt Stap 3 opnieuw uitgevoerd.
- Stap 7 vergelijkt de nieuwe detectierun rechtstreeks met de bevroren Ground Truth en met een vorige modelrun.
- Alleen FP, FN, geometrie-afwijkingen en merged-cell gevallen worden als vervolg-review getoond.
- Vervolg-reviewbeslissingen zijn run-scoped en veranderen de Ground Truth niet automatisch.
- Een verdachte GT wordt bewust teruggestuurd naar Stap 4 voor expliciete correctie.

Voor bestaande projecten kan Stap 7 de eerste baseline reconstrueren uit de oorspronkelijke Stap-4 reviews en de reeds aanwezige table-cell dataset. De actuele Stap-3-output wordt bij het eerste openen als nieuwe vergelijking-run vastgelegd; opnieuw detecteren is daarvoor niet vereist zolang de huidige diagnostics aanwezig zijn.
