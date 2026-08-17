# IsalaOCR v3.5.14

## Duidelijke vergelijking tussen nieuw en oud model

De processtap **Modellen vergelijken** is opnieuw opgebouwd als een echte side-by-side vergelijking:

- links staat altijd het nieuwste custom model;
- rechts staat altijd het oude officiële baseline-model;
- beide modelbeoordelingen hebben een eigen uitvoerknop;
- **Alles uitvoeren** zet de nieuwe evaluatie, oude evaluatie en vergelijking in de juiste volgorde in de wachtrij;
- de gezamenlijke vergelijking kan pas los worden gestart wanneer beide evaluaties aanwezig zijn;
- een geldig vergelijkingsresultaat wordt niet langer als mislukte taak gemarkeerd wanneer het nieuwe model niet wint.

De vergelijking bevat voortaan:

- totaalscores voor exact match en character error rate;
- aantallen waarbij alleen het nieuwe of alleen het oude model correct is;
- vergelijking per veld;
- vergelijking per individuele ROI-crop met verwachte waarde, modeluitvoer en confidence;
- filters voor verschillen, verbeteringen, verslechteringen, fouten en alle samples;
- een expliciet eindoordeel zonder normalisatie van OCR-uitvoer.

Vergelijkingen uit oudere versies blijven leesbaar. Voer actie 14 opnieuw uit om de nieuwe detailweergave per veld en per crop te vullen.
