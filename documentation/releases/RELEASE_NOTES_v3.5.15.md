# IsalaOCR v3.5.15

## Trainbare normalisatie van rijheaders

De workflow bevat nu een afzonderlijke processtap **Rijheaders trainen** tussen detectie en ROI-beoordeling.

In deze tab kan per uitgelezen rijheader worden beoordeeld:

- welke tekst de locator daadwerkelijk heeft gelezen;
- aan welk geconfigureerd veld die header moet worden gekoppeld;
- wat de correcte, leesbare rijheadertekst is;
- of de koppeling correct, onbruikbaar, uitgesteld of nog open is.

Nieuwe beoordelingen staan standaard op **Koppeling klopt**, zodat alleen afwijkingen hoeven te worden aangepast.

De knop **Normalisatiemodel trainen** bouwt een lokaal, deterministisch aliasmodel. Dit model leert bijvoorbeeld dat `ED VoIume` of `ED V0lume` dezelfde betekenis heeft als `ED Volume`. De numerieke OCR-waarde en het herkenningsmodel voor de waarde worden hierbij niet gewijzigd.

De knop **Trainen en DICOMs opnieuw detecteren** bouwt eerst het normalisatiemodel en plaatst daarna de detectieactie opnieuw in de wachtrij. Nieuwe detecties gebruiken de geleerde headeraliassen direct.

Aanvullende wijzigingen:

- rijheadercrops en de bijbehorende coördinaten worden apart opgeslagen;
- de database bewaart een onafhankelijke reviewstatus voor rijheaders;
- een rijheaderbeoordeling wordt automatisch heropend wanneer de uitgelezen headertekst verandert;
- dubbelzinnige aliassen die binnen hetzelfde paneel aan meerdere velden zijn gekoppeld worden niet geactiveerd;
- dezelfde headeralias mag wel afzonderlijk voor het linker- en rechterventrikel worden geleerd;
- de workflow bestaat nu uit veertien afzonderlijke processtappen.
