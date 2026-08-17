# Migratie

## Naar v3.7.0 – Detection Pipeline Separation

Versie 3.7.0 scheidt field localization van mapping/waarde-OCR. De database migreert automatisch naar schema v11 en bestaande recognition-samples, reviews, datasets en geregistreerde modellen blijven behouden.

Aanbevolen upgrade:

1. stop actieve workers/containers en maak een back-up van `training/workspace` en `models`;
2. pak v3.7.0 over de bestaande projectmap uit;
3. start `START.cmd` en voer actie **1** uit;
4. voer actie **2** uit om neutrale field candidates te detecteren;
5. beoordeel/corrigeer de geometrie in **Detection Review Studio**;
6. bouw en valideer de COCO localization dataset met acties **5** en **6**;
7. train/evalueer een field detector met acties **7–10** en activeer alleen een model dat de gate haalt met actie **11**;
8. voer actie **12** uit om opnieuw met het actieve model te detecteren en controleer actie **13**;
9. ga pas na de geopende Detection Gate verder met Mapping Studio en waarde-OCR (acties **20+**).

Oude semantic/generic detections mogen als migratie-informatie blijven bestaan, maar gelden niet als localization ground truth. Definitieve cropgeometrie in Pipeline B moet uit Pipeline A komen.

> De onderstaande migraties zijn historische instructies voor oudere releases; de toenmalige menunummers gelden niet voor v3.7.0.

## Van v3.1.x naar v3.2.0

Versie 3.2 vervangt de vaste rijvolgorde van de trainingscollector door dynamische schermlabel- en rijlokalisatie.

Na uitpakken over de bestaande map:

1. stop en herbouw de labeler via menuoptie 4 en daarna 3;
2. voer menuoptie 2 opnieuw uit om alle crops dynamisch te genereren;
3. controleer `training/workspace/locator_overlays`;
4. beoordeel eerst de wachtrij `Extractie-fallbacks`;
5. bouw pas daarna een nieuwe dataset.

De bestaande `samples.sqlite3` wordt automatisch gemigreerd. Ongewijzigde goedgekeurde crops blijven goedgekeurd. Wanneer de croppixels of extractiemethode veranderen, wordt de oude beoordeling in `review_history` bewaard en komt alleen die sample opnieuw op `pending`.

## Van v2.0.1 naar v3.0.0

De normale OCR-route blijft compatibel. Bestaande lokale modelbestanden onder `models/paddlex` kunnen behouden blijven.

Nieuwe onderdelen:

- `training/` voor crops, datasets, runs en modelregister;
- `training_runtime/` voor PaddleX fine-tuning;
- `Dockerfile.training`;
- extra Docker Compose-services;
- `.cmd`-starters en trainingsscripts;
- `models/active-recognition` voor het geactiveerde custom model.

Aanbevolen upgrade:

1. stop containers met `docker compose down --remove-orphans`;
2. maak een back-up van projectmap en `models`;
3. pak het upgradepakket over de bestaande map uit;
4. start `TRAINING_MENU.cmd`;
5. kies eerst voorbereiding en cropcollectie;
6. activeer nog geen model voordat baseline/custom evaluatie op dezelfde testset is afgerond.

## Van legacy v1

De oude code staat uitsluitend onder `legacy-v1/`. Zij wordt niet door de nieuwe containers uitgevoerd. De 14 oude extensieloze DICOM's staan onder `input/test-dicoms/`.

Belangrijkste verschillen:

- modellen worden één keer geladen in plaats van per afbeelding;
- vaste ROI's en recognition-only training;
- geen patiëntafgeleide bestandsnamen;
- netwerkloze normale runtime;
- gestructureerde output en versievaste modelpromotie;
- exacte trainingslabels zonder normalisatie.
