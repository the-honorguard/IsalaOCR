# IsalaOCR 3.11.13

## Table reviewer: manual cells and overlap selection

- Handmatig toegevoegde cellen kunnen op het canvas worden geselecteerd, aangepast en verwijderd.
- `Kader aanpassen` gebruikt voor handmatige cellen dezelfde resize-handgrepen als Paddle-kandidaten en slaat de nieuwe geometrie persistent op.
- De vaste reviewbalk toont een directe `Handmatige cel verwijderen`-actie wanneer een handmatige cel is geselecteerd.
- Selectiemarkers staan in een aparte overlay boven alle kaders. Hierdoor blijft het bij overlappende cellen mogelijk het bedoelde kader via zijn marker te selecteren.
- De reviewer legt nu expliciet uit dat één kader één functionele cel voorstelt. Als een Paddle-kader meerdere echte cellen/rijen samenvoegt, wordt het als merged detectiefout afgekeurd en worden de correcte cellen apart toegevoegd.
