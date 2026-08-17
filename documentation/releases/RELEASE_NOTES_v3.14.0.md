# IsalaOCR 3.14.0

## Versioned training loop: GT, model, detectierun en review zijn nu gescheiden

Deze release maakt de iteratieve table-cell training expliciet run-aware. De kernregel is voortaan:

**Ground Truth is persistent; predictions en reviews horen bij precies één detectierun en één modelversie.**

Daardoor kan het activeren van een nieuw model nooit meer oude Stap-3-output opnieuw als nieuwe modeloutput laten verschijnen.

### Nieuwe run-identiteit

- Iedere complete Stap-3 table-first detectie krijgt één `detection_batch_id`.
- Per bron wordt vastgelegd welk table-cell model, welke trainingsrun en welke modeldataset daadwerkelijk voor die detectie zijn gebruikt.
- Stap 7 leidt de modelidentiteit uit deze bevroren detectiemetadata af en niet uit het model dat later toevallig actief is geworden.
- Als model v2 actief is maar de laatste detectie nog van v1 komt, blokkeert Stap 7 de actieve review en vraagt expliciet om Stap 3 opnieuw uit te voeren.
- Oude runs blijven beschikbaar als historie/vergelijking, maar zijn niet langer de actieve review.

### Nieuwe reviewcyclus

- Alleen de nieuwste complete Stap-3-run is schrijfbaar in Stap 7.
- Historische runs zijn read-only.
- Reviewbeslissingen blijven per `run_id` opgeslagen en worden nooit overgenomen naar een nieuwe detectierun.
- Bij `0 open` toont Stap 7 een afgeronde reviewronde met de aantallen modelmissers, functioneel correcte geometrie en GT-controles.

### Reviewfeedback wordt trainingsinput

- De nieuwste volledig afgeronde Stap-7-review wordt onderdeel van de datasetstatus.
- Alleen expliciete `Model fout`-beslissingen worden hard examples.
- FN, FP en geometrie-modelmissers krijgen in TRAIN een effectieve weging van x3; merged-cell modelmissers x4.
- `Functioneel correct` wordt niet extra getraind en dus niet als fout bestraft.
- Hard-example oversampling gebeurt uitsluitend in TRAIN. VAL en TEST blijven onaangeroerd zodat modelvergelijking eerlijk blijft.
- Een nieuwere perfecte/afgeronde run vervangt oudere hard-example feedback, zodat oude missers niet permanent overgewogen blijven.

### Vervolgtraining vanaf het actieve custom model

- Trainingsronde 2+ probeert de `.pdparams` checkpoint van het actieve custom model te gebruiken.
- Vervolgtraining gebruikt standaard een lagere learning rate (`3e-5`) en 40 epochs wanneer geen expliciet aantal epochs is opgegeven.
- Als de originele trainingscheckpoint niet meer beschikbaar is, valt de runner veilig terug op de officiële RT-DETR-L wireless table-cell pretrain.
- Modelmetadata bevat nu `parent_model_id`, `training_mode`, learning rate en epochs, zodat de lineage zichtbaar blijft.

### Dataset- en UI-state

- Dataset-currentness kijkt nu naar zowel de canonieke GT-fingerprint als de nieuwste afgeronde Stap-7-feedbackfingerprint.
- Een afgeronde nieuwe review kan de dataset dus bewust verouderen, ook wanneer de GT zelf niet is aangepast.
- Stap 6 prioriteert voortaan de echte volgende actie: dataset opnieuw bouwen, valideren, vervolgtrainen, activeren of opnieuw detecteren.
- Oude detectorruns kunnen na GT-wijzigingen voor metrische vergelijking in-memory tegen de huidige GT worden herberekend wanneer de panelgeometrie ongewijzigd is; de bevroren predictions zelf worden niet herschreven.
