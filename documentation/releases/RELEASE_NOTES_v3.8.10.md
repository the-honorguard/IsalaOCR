# IsalaOCR 3.8.10 — modernere selectie in Detection Review Studio

Detection Review Studio gebruikt nu een directer canvas-editor-model. Selecteren en geometrie aanpassen zijn bewust van elkaar gescheiden.

- Gewoon klikken selecteert een crop zonder deze te verplaatsen.
- Dubbelklik of `E` activeert expliciete kaderbewerking voor precies één crop.
- Sleep op lege ruimte om direct een marquee/selectiegebied te tekenen; een aparte Selectievenster-modus is niet meer nodig.
- De marquee toont live welke kandidaten geraakt worden en gebruikt zowel middelpunt als betekenisvolle overlap.
- Shift/Ctrl tijdens slepen voegt toe; Alt trekt uit de selectie af.
- `Ctrl+A` of **Alles zichtbaar** selecteert alle kandidaten binnen het huidige filter.
- Kandidatenkaarten hebben een expliciet selectierondje zodat batches niet afhankelijk zijn van modifier-toetsen.
- Hover op een kaart markeert het bijbehorende kader op de bronafbeelding en andersom.
- Multi-select toont een floating batch-toolbar voor bevestigen, meenemen, niet nodig en detectiefout.
- De bestaande backend-API, reviewstatussen en trainingssemantiek zijn ongewijzigd.

De zware training-images blijven op hun bestaande training-imageversie; deze UI-release forceert geen rebuild van CPU/GPU-training-images.
