# IsalaOCR v3.3.8 — Compose run flag repair and persistent training-image revision

## Probleem

Docker Compose ondersteunt `--no-build` voor `compose up` en `compose create`, maar niet voor `compose run`.
Versie 3.3.7 bouwde de CPU- en GPU-trainingimages correct, maar stopte daarna bij het starten van
`training-setup` met `unknown flag: --no-build`.

## Oplossing

- Vervangt de ongeldige `docker compose run --no-build`-aanroepen door `docker compose run --pull never`.
- Controleert vooraf met `docker image inspect` dat de vereiste trainingimage lokaal aanwezig is.
- Slaat de zware trainingimage-revisie afzonderlijk op in `TRAINING_IMAGE_VERSION`.
- Houdt voor deze host-script-only hotfix de bestaande image-revisie `3.3.7` aan.
- Menuoptie 1 slaat CPU- en GPU-builds over wanneer deze images al lokaal aanwezig zijn.
- Voorkomt daardoor dat de reeds gedownloade CUDA-base en PaddlePaddle GPU-wheel opnieuw worden opgehaald.
- Wijzigt geen DICOMs, reviews, labels, datasets, modellen of trainingsruns.

## Verwachte vervolgstap

Na installatie opnieuw menuoptie 1 uitvoeren. De bestaande images
`isalaocr-training-cpu:3.3.7` en `isalaocr-training-gpu:3.3.7` worden hergebruikt.
Alleen de nog ontbrekende pretrained recognition weights worden voorbereid.
