# IsalaOCR v3.3.7 — persistent training-image cache and PaddleX metadata repair

## Problemen

1. De installatie van PaddlePaddle/PaddleX en de buildverificatie stonden in één Docker `RUN`-instructie. Iedere wijziging aan de verificatie maakte daardoor ook de zware dependencylaag ongeldig.
2. De GPU-base-image kan oude PaddleX 3.3.11-distributiemetadata blijven aanbieden via een tweede Python-locatie. Pip installeerde PaddleX 3.7.2 correct, maar `importlib.metadata.version("paddlex")` koos het verouderde record en brak de build af.
3. Menuoptie 1 bouwde alleen de CPU-trainingimage; de grote GPU-base werd pas bij het starten van optie 10 opgehaald.

## Oplossingen

- De zware pip-installatie staat in een afzonderlijke stabiele Dockerlaag.
- Buildverificatie staat in een latere, lichte laag.
- De checksum-gecontroleerde source-overlay `/opt/paddlex-source` is de autoritatieve PaddleX 3.7.2-runtime voor training.
- Alle zichtbare PaddleX-distributiemetadata wordt alleen nog diagnostisch gerapporteerd.
- Menuoptie 1 bouwt zowel `trainer-cpu` als `trainer-gpu` vooraf.
- `training-setup` en `trainer-cpu` delen dezelfde versievaste CPU-image.

## Verwacht gedrag

De eerste GPU-voorbereiding downloadt de CUDA-base en PaddlePaddle GPU-wheel één keer. Daarna worden deze uit lokale Dockerlagen/BuildKit-cache hergebruikt. Het verwijderen van Docker images, builder cache of Docker Desktop-data maakt een nieuwe download noodzakelijk.
