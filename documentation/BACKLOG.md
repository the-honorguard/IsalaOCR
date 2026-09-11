# IsalaOCR backlog

## Mapping Studio opnieuw ontwerpen — label- en tabelgestuurde mapping

**Status:** gepland

De huidige Mapping Studio is te veel gericht op relationele crops en ROI-
beoordeling. Er komt een nieuwe Studio waarin het uitgelezen label de primaire
ingang is voor de mapping.

### Gewenste werking

- lees alle bruikbare labels met OCR;
- koppel ieder label via aliassen aan een functioneel mappingveld;
- gebruik tabel-, panel-, rij- en waarde-kolomcontext om de bijbehorende
  waarde-cel te bepalen;
- gebruik ROI/crop alleen voor waarde-OCR, controle en datasetexport;
- behandel lege of onleesbare waarde-cellen expliciet als `no_value` of
  `unreadable`;
- toon voorstellen eerst als open/suggested en bevestig ze pas handmatig;
- toon de bronrelatie compact met label, veld, context, rij, waarde en reden
  van de match.

### Afbakening

De bestaande Mapping Studio blijft voorlopig beschikbaar als legacy-flow. De
nieuwe Studio wordt als afzonderlijke interface en workflow gebouwd. Canonical
Detection-GT, tabelstructuur en Recognition-GT blijven de onderliggende bronnen;
de mappinglogica kiest niet langer op basis van ROI-geometrie.

### Acceptatiecriteria

- oude bevestigde mappings worden niet stilzwijgend hergebruikt in een nieuwe
  voorstelrun;
- een label kan naar één voorstelveld worden gemapt met zichtbare context;
- de waarde komt aantoonbaar uit dezelfde tabelrij en waarde-kolom;
- een gebruiker kan accepteren, wijzigen, afwijzen of als leeg/onleesbaar
  markeren;
- de nieuwe mappingresultaten kunnen door de bestaande value-OCR- en exportflow
  worden gebruikt.
