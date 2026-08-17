# IsalaOCR v3.7.5

## Detection Review multiselect

Deze release maakt bulkbeoordeling van grote localization-reviewsets sneller.

- **Shift-klik** in de kandidatenlijst selecteert een reeks vanaf het vorige anker.
- **Ctrl/Cmd-klik** voegt individuele kandidaten aan de selectie toe of verwijdert ze.
- **Selectievenster** (knop of `S`) laat je een rechthoek over de bronafbeelding slepen. ROI-kaders waarvan het midden in het venster ligt worden geselecteerd. Houd Shift/Ctrl ingedrukt tijdens het slepen om aan een bestaande selectie toe te voegen.
- `Correct`, `Detectie fout`, `Toch meenemen` en de zeven directe **Niet relevant**-redenen worden als batchactie toegepast.
- De inspector toont het aantal geselecteerde kandidaten. Bij multiselect is geometry editing uitgeschakeld; resizen en `Aangepast opslaan` blijven single-crop acties.
- `Esc` wist de selectie of verlaat selectiemodus.
- De batch endpoint valideert alle kandidaat-ID's en accepteert maximaal 2000 kandidaten per request.

Er is geen databaseschemamigratie nodig en de zware training-image revision blijft `3.7.0`.
