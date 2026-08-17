# IsalaOCR v3.5.12

## Vastlopende webtaken hersteld

- De webworker gebruikt niet langer de automatische PowerShell-variabele `$args` om een actieproces op te bouwen.
- Acties worden met een expliciete, niet-interactieve opdrachtregel gestart: `powershell.exe -NonInteractive -File ... action <id>`.
- De tijdelijke CMD-wrapper wordt via `call` uitgevoerd en geeft de werkelijke exitcode terug.
- Hierdoor kan PowerShell niet meer zonder scriptargumenten in een interactieve prompt blijven hangen.

## Veilige worker-update en taakrecovery

- Een worker uit een oudere release wordt inclusief onderliggende processen beëindigd voordat de nieuwe worker start.
- Taken die na een onderbroken of bijgewerkte worker nog als actief geregistreerd staan, worden veilig als mislukt gemarkeerd met exitcode 125.
- Deze taken kunnen daarna vanuit Wachtrijbeheer opnieuw worden uitgevoerd.
- De workerstatus vermeldt voortaan of op de eerste scriptuitvoer wordt gewacht of dat de actie daadwerkelijk uitvoer produceert.
