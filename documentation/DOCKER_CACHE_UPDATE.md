# Docker dependency cache update 3.2.3

## Probleem

De oude Dockerfile kopieerde `src/` voordat `pip install` werd uitgevoerd.
Iedere broncode-update maakte daardoor de volledige dependencylaag ongeldig en
installeerde PaddleOCR, PaddlePaddle, OpenCV en DICOM-codecs opnieuw.

## Nieuwe werking

1. `requirements-runtime.txt` wordt eerst gekopieerd.
2. Externe dependencies worden in een stabiele laag geïnstalleerd.
3. BuildKit bewaart pip- en apt-downloads in persistente buildcaches.
4. Pas daarna worden `pyproject.toml` en `src/` gekopieerd.
5. De lokale applicatie wordt met `--no-deps` geïnstalleerd.

De eerste build na deze update is nog één keer volledig. Volgende builds horen
de dependency-installatiestap als `CACHED` te tonen, zolang de requirements niet
veranderen.

## Cache controleren

```powershell
docker system df
docker buildx du
```

## Cache bewust verwijderen

```powershell
docker builder prune -f
```

Na deze opdracht moeten dependencies bij de volgende build opnieuw worden
opgehaald. Gebruik dit daarom alleen bij opslagproblemen of een bewust schone
rebuild.
