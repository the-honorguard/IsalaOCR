# Upgrade naar IsalaOCR v3.8.4

## Vooraf

1. Laat actieve jobs afronden of stop ze bewust.
2. Maak een back-up van `training`, `models`, `input` en eventueel `output`.
3. Pak de v3.8.4-ZIP uit over de bestaande projectmap.
4. Start `START.cmd`.

## Automatische projectmigratie

De eerste start maakt project `cmr_testcase_01` aan en migreert de bestaande 3.7.x werkruimte naar `training/workspace/projects/cmr_testcase_01`. Detection reviews, mappings, localization datasets/runs/models, recognition datasets/runs en overige projectartefacten blijven behouden.

De bestaande recognition registry en actieve recognition-modelmap worden bij eerste gebruik naar een projectspecifieke namespace gekopieerd. De database blijft schema v12.

Het bestaande project houdt `/input` als inputpad zodat de huidige testcase direct blijft werken. Nieuwe projecten krijgen standaard `/input/projects/<project-id>`; maak die map op de host en plaats daar de documenten voor die use-case.

## Gewijzigd beoordelingsmechanisme

Je hoeft niet langer alle kandidaten af te ronden voordat een localization-dataset kan worden gebouwd. Alleen expliciet beoordeelde voorbeelden tellen:

- positief: Correct, Aangepast, handmatig toegevoegd;
- negatief: expliciet afgekeurd of Niet nodig voor dit project;
- onbeoordeeld: volledig genegeerd.

Redenen zijn optioneel en dienen voor analyse, niet als modeltarget. Bij gedeeltelijk beoordeelde bronbeelden gebruikt de datasetbuilder lokale contextpatches zodat onbekende velden niet als achtergrond worden aangeleerd.

## Nieuwe use-case

Maak via **Projecten beheren** een leeg project, kies een use-case template en gebruik een eigen inputsubmap. Dupliceer een bestaand project alleen voor experimenten binnen dezelfde use-case; cross-use-case duplicatie wordt geblokkeerd.

## v3.8.4

The preparation path is consolidated under Stap 1 · Voorbereiding. The page can prepare everything or independently install inference/table models, the CPU detector stack, the GPU OCR-recognition stack, the dedicated GPU PaddleDetection/PicoDet-S stack, and the PP-OCRv6 pretrained recognition weight. GPU field-detector training now uses `isalaocr-training-gpu-detection:3.8.4`; recognition training uses `isalaocr-training-gpu:3.8.4` without PaddleDetection.

PaddleDetection installation omits its deprecated `sklearn==0.0` compatibility shim through PaddleX dependency replacement. PaddlePaddle remains pinned to 3.2.2. Existing project workspaces, reviews, datasets and registries are preserved.

## v3.8.3

Stap 1 · Voorbereiding can rebuild training image revision `3.8.3` with PaddlePaddle 3.2.2. This replaces the 3.3.0 CPU runtime that can crash PicoDet-S inference in the upstream oneDNN/PIR executor. Existing project workspaces, review databases, datasets and registries are preserved.

## v3.8.2

Stap 1 · Voorbereiding rebuilds the runtime dependency layer once when PaddleOCR `doc-parser` support for PP-StructureV3 is missing. Existing project workspaces and model registries are preserved.
