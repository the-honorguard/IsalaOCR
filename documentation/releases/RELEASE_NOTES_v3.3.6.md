# IsalaOCR v3.3.6 — GPU build/runtime boundary repair

## Probleem

`trainer-gpu` installeerde `paddlepaddle-gpu==3.3.0` correct, maar importeerde `paddle` daarna nog tijdens de Docker-build. De CUDA-wheel laadt daarbij `libpaddle.so`, dat op zijn beurt `libcuda.so.1` nodig heeft. Die driverbibliotheek wordt niet in een image gebakken en is normaal niet beschikbaar tijdens `docker build`; Docker/NVIDIA koppelt haar pas wanneer de uiteindelijke container met GPU-toegang wordt gestart.

## Oplossing

- De build gebruikt alleen `importlib.metadata`, `importlib.util.find_spec` en een bestandscontrole op `libpaddle.so`.
- De geïnstalleerde versies blijven vastgezet op PaddlePaddle 3.3.0 en PaddleX 3.7.2.
- `paddle` wordt pas geïmporteerd nadat `trainer-gpu` met `gpus: all` is gestart.
- Voor training, PaddleX-evaluatie en export wordt gecontroleerd of de runtime CUDA ondersteunt en minimaal één GPU ziet.

## Upgrade

Pak de rootless ZIP over de bestaande projectmap uit en voer menuoptie 10 opnieuw uit. Optie 1, labeling en datasetbouw hoeven niet opnieuw.
