# IsalaOCR 3.4.0

## Centrale launcher

De hoofdmap bevat alleen `START.cmd`. Alle oude losse `.cmd`-wrappers zijn verwijderd. De launcher ondersteunt:

```text
START.cmd
START.cmd check
START.cmd check <actie 1-16>
START.cmd repair
START.cmd action <actie 1-16>
```

## Automatische preflight

Iedere menuactie wordt vóór uitvoering gecontroleerd. Een mislukte verplichte controle blokkeert de actie met een concrete herstelmelding.

De preflight controleert projectstructuur, Docker Desktop, Compose, Windows-schrijfaccess, Docker UID/GID-rechten en actiespecifieke modellen/datasets/runs. GPU-training controleert daarnaast de daadwerkelijke PaddlePaddle CUDA-runtime.

## Check-only mode en algemene controle

- `C` schakelt check-only mode in het menu in.
- Optie `17` controleert alle 16 acties zonder ze uit te voeren.
- JSON-rapporten worden onder `training/workspace/diagnostics` opgeslagen.

## Rechtencontrole en herstel

Er zijn afzonderlijke Docker-services voor:

- controle als UID/GID `10001:10001`;
- beperkte reparatie als root met alleen `CHOWN`, `DAC_OVERRIDE` en `FOWNER`.

De reparatie richt zich op `output`, `models/training`, `models/active-recognition`, `training/workspace` en `training/registry`.

## Opgeruimde structuur

De inhoud is ondergebracht in `application`, `automation`, `documentation`, `infrastructure` en `project`. De bestaande datamappen `input`, `output`, `models` en `training` blijven op hun huidige plaats, zodat upgrades geen gebruikersdata hoeven te verplaatsen.

## Docker-buildscheiding

Build-only services en runtime-services voor de zware CPU/GPU-trainingimages zijn gescheiden. Normale validatie, training, export en controle gebruiken uitsluitend vooraf gebouwde images en kunnen daardoor niet ongemerkt de volledige PaddleX/CUDA-stack opnieuw bouwen.

De trainingimage-revisie blijft `3.3.11`; bestaande lokale CPU- en GPU-images kunnen worden hergebruikt.
