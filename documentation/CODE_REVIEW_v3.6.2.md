# Code review v3.6.2 – functionaliteit, effectiviteit en UX

Datum: 2026-08-07

## Scope

Review van de generieke detectie-, Paddle-tabel-, Mappingstudio-, ROI-materialisatie- en beoordelingsflow in IsalaOCR 3.6.2. De review is uitgevoerd vóór de wijzigingen voor 3.6.3. De bestaande testset is eerst ongewijzigd uitgevoerd: **190 tests geslaagd, 14 overgeslagen**.

## Bevindingen en uitgevoerde wijzigingen

### Hoog – een mapping verwijderen in Mappingstudio verwijderde de oude koppeling niet betrouwbaar

De relationele mappingformulieren sloegen alleen niet-lege selecties op. Wanneer een eerder gekoppelde relatie op **— niet mappen —** werd gezet, kon de oude `field_mapping` blijven bestaan. Daardoor kon de output nog een veld bevatten dat de gebruiker visueel had verwijderd.

**Aangepast:** Mappingstudio synchroniseert nu expliciet zowel toevoegingen als verwijderingen. Een lege selectie betekent daadwerkelijk verwijderen.

### Hoog – gewijzigde mappings konden reeds goedgekeurde ROI- en waardebeoordelingen blijven gebruiken

Een bestaande `mapped_generic`-sample kon geldig blijven nadat de mapping, de gekoppelde relatie of de detectiegeometrie was veranderd. Daarmee bestond het risico dat een oude crop later opnieuw werd herkend of in een dataset terechtkwam.

**Aangepast:** samples van gewijzigde/verwijderde mappings worden `mapped_generic_stale`, hun ROI-beoordeling gaat terug naar `pending` en eerdere waardebeoordeling wordt ongeldig gemaakt met behoud van reviewhistorie. Stale samples zijn uitgesloten van actieve ROI- en waardeflows totdat **Mapping toepassen** opnieuw is uitgevoerd.

### Hoog – detectie opnieuw uitvoeren kon een orphan mapping achterlaten

Wanneer nieuwe detectie andere block-/relation-ID's opleverde, werd een bevestigde mapping voorheen teruggezet naar `suggested`, terwijl die mapping nog naar inmiddels verwijderde blokken verwees. Door de joins in de Mappingstudio was zo'n mapping vervolgens niet meer zichtbaar, terwijl de rij in SQLite nog wel bestond.

**Aangepast:** mappings naar verdwenen detectiegeometrie worden nu verwijderd nadat hun gematerialiseerde ROI is ingetrokken. De normale suggestion-engine kan daarna op de nieuwe detecties een nieuwe, geldige voorzet maken.

### Hoog – opslaan van meerdere mappings was niet atomair

Het webformulier voerde losse databasebewerkingen uit. Wanneer een latere rij in dezelfde save faalde, konden eerdere rijen al zijn verwijderd of gewijzigd.

**Aangepast:** relationele mappings worden nu met `sync_relation_mappings()` als één SQLite-transactie gevalideerd en opgeslagen. Alle relation- en field-ID's worden vooraf gecontroleerd; bij een fout wordt niets van de formulierwijziging toegepast.

### Middel – één visueel waargenomen waarde kon aan meerdere functionele velden worden gekoppeld

De database was uniek op `(source_id, field_key)`, maar niet op de waargenomen relatie/waarde. Vooral handmatige mappings konden daardoor één `value_block` meerdere keren semantisch gebruiken.

**Aangepast:** relationele én handmatige mappings bewaken nu één functionele bestemming per waargenomen value block. Herkoppelen retireert de oude mapping en de bijbehorende oude ROI.

### Middel – automatische voorstellen bleven na herberekenen staan

`Voorstellen herberekenen` voegde nieuwe suggesties toe, maar verwijderde oude automatische suggesties die niet langer aan de scoregrens voldeden niet altijd. Daardoor kon de lijst een oude scoringssituatie weergeven.

**Aangepast:** alleen niet-bevestigde suggesties worden vóór herberekening verwijderd. Bevestigde mappings blijven onaangetast. De nieuwe set is daardoor deterministisch.

### Middel – PP-Structure OCR werd te grof als fallback gebruikt

Wanneer full-page OCR ook maar één token bevatte, werd PP-Structure's interne tabel-OCR voor de gehele tabel niet meer gebruikt. Daardoor konden cellen leeg blijven terwijl Paddle voor die specifieke cel wel tekst had.

**Aangepast:** de fallback is nu **per cel**. Full-page OCR blijft voorkeursbron; alleen een cel zonder passende full-page token gebruikt de interne table-OCR.

### Middel – overlappende Paddle-cellen konden OCR-tekst dupliceren

OCR-tokens werden op basis van hun middelpunt per cel bekeken. Bij licht overlappende cell boxes kon hetzelfde token in meerdere cellen terechtkomen.

**Aangepast:** ieder OCR-token wordt maximaal aan één best passende cel toegewezen op basis van overlapdekking, celdekking en center containment.

### UX – Mappingstudio was te lang en onvoldoende taakgericht

Een bron kan ruim honderd relaties produceren. Primaire meetwaarden, referentiewaarden, OCR-relaties en Paddle-relaties stonden in één lange lijst en de output-preview bood onvoldoende ruimtelijke context.

**Aangepast:** Mappingstudio heeft nu:

- zoeken op label, waarde en functioneel veld;
- filters voor Paddle/OCR, mappingstatus en confidence;
- secundaire/referentiewaarden standaard verborgen;
- sticky live output-preview;
- bronafbeelding met afzonderlijke label- en value-overlay;
- vorige/volgende navigatie en `Alt+↑/↓` voor snelle controle;
- veldselecties gegroepeerd per functionele groep;
- visuele dirty-state voor gewijzigde mappings.

### UX – dubbele functionele veldkeuzes waren pas na opslag zichtbaar

Hetzelfde functionele veld kon in het formulier aan meer dan één relatie worden geselecteerd. Dit gaf onduidelijk semantisch resultaat.

**Aangepast:** dubbele veldselecties worden direct gemarkeerd, opslaan wordt geblokkeerd en de server valideert dezelfde regel opnieuw.

### UX – bulkbevestiging van automatische voorstellen was te agressief

Alle automatische voorstellen vooraf selecteren is ongeschikt wanneer mapping semantische betekenis bepaalt.

**Aangepast:** alleen voorstellen met een mapping-confidence van minimaal 82% zijn vooraf aangevinkt. De gebruiker houdt expliciete controle.

## Resultaat

De wijzigingen veranderen de rolverdeling niet: detectie blijft generiek, Mappingstudio kent betekenis toe, ROI-review beoordeelt alleen geometrie en waarde-review alleen OCR-inhoud. De review heeft vooral de grenzen tussen die stappen strenger gemaakt en de Mappingstudio geschikt gemaakt voor snelle controle van grotere aantallen detecties.
