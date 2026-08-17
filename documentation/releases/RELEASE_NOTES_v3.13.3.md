# IsalaOCR 3.13.3

## Geschatte duur bij workflowacties

Alle worker-backed workflowacties tonen nu vóór het starten een compacte tijdsindicatie, bijvoorbeeld `⏱ ± 10–30 sec`, `⏱ ± 2–10 min` of `⏱ ± 1–4 uur`.

- De schatting staat zichtbaar onder de actieknop.
- Detailinformatie staat als tooltip op knop en tijdslabel.
- Kleine technische `Check`-knoppen krijgen alleen een tooltip om de voorbereidingstabel compact te houden.
- Schattingen zijn ranges en houden expliciet rekening met verschil tussen eerste downloads/builds en warme Docker/modelcaches.
- Table-cell GPU-training gebruikt voor het huidige `small-reviewed` profiel `± 8–20 min`; CPU-training `± 1–4 uur`.
- Navigatie- en editoracties worden niet gelabeld omdat die direct reageren en geen worker-taak starten.
