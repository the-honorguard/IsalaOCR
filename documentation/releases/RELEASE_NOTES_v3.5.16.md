# IsalaOCR v3.5.16

## Correcte positionering van ROI-kaders

De interactieve kaders in **Detectieweergave** en **ROI beoordelen** worden nu gepositioneerd ten opzichte van de werkelijk gerenderde bronafbeelding.

De eerdere viewer gebruikte de volledige hoogte van het gridvak als coördinatenstelsel. Wanneer de lijst met gedetecteerde velden hoger was dan de afbeelding, werd de viewer verticaal uitgerekt. De afbeelding bleef bovenaan op de juiste beeldverhouding staan, maar de procentuele Y-coördinaten van de kaders werden berekend over de uitgerekte viewer. Daardoor schoven kaders omlaag en konden ze in het zwarte gebied onder de afbeelding terechtkomen.

De oplossing gebruikt nu een afzonderlijke `image-overlay-stage`:

- de bronafbeelding bepaalt exact de hoogte en beeldverhouding van deze stage;
- alle kaders staan binnen dezelfde stage;
- het omringende gridvak en de scrollcontainer mogen onafhankelijk groter of kleiner worden;
- breedte- en hoogteattributen van de bronrender voorkomen verschuiving tijdens het laden;
- dezelfde correctie geldt voor zowel Detectieweergave als ROI beoordelen.

Bestaande ROI-coördinaten en beoordelingen hoeven niet opnieuw te worden aangemaakt. Dit was een uitsluitend visuele fout in de webinterface.
