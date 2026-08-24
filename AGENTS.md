# IsalaOCR diagnose-workflow

## Terminallogs lezen

Elke start via `START.cmd` schrijft de volledige uitvoer van `git pull`, de
launcher, preflight en de gekozen workflowactie naar:

```text
diagnostics/terminal-logs/startup-YYYYMMDD-HHMMSS-PID.log
```

De nieuwste run staat altijd ook op:

```text
diagnostics/terminal-logs/latest.log
```

Gebruik vanuit PowerShell:

```powershell
. .\automation\powershell\read-latest-logs.ps1
Read-IsalaLatestLogs
```

Voor alleen vermoedelijke problemen:

```powershell
. .\automation\powershell\read-latest-logs.ps1
Read-IsalaLatestLogs -ErrorsOnly
```

Kort commando voor dezelfde foutanalyse:

```powershell
. .\automation\powershell\read-latest-logs.ps1
errorlog
```

`errorlog` doorzoekt standaard de 10 meest recente startup-logs, met de nieuwste run eerst,
naar onder andere errors, exceptions, failures, time-outs, stale-statussen en
blokkades. Gebruik `errorlog -Tail 500` voor een grotere foutcontext.
Gebruik `errorlog -RunCount 20` om meer runs te doorzoeken.

Markeer een log nadat de oorzaak is opgelost:

```powershell
errorlog -MarkHandled -LogPath "C:\pad\naar\startup-20260824-100623-32332.log" -Reason "Healthcheck retry logging opgelost"
```

Behandelde logs blijven fysiek bestaan en kunnen als referentie worden gelezen
met `errorlog -IncludeHandled`, maar worden standaard overgeslagen. Codex mag
geen nieuwe fix starten op uitsluitend een behandelde log; gebruik die alleen
als historische context wanneer een nieuwe onbehandelde fout ermee samenhangt.

Voor een overzicht van beschikbare runs:

```powershell
& .\automation\powershell\read-latest-logs.ps1 -List
```

Wanneer de gebruiker vraagt om logs te controleren, moet Codex eerst de
nieuwste log lezen met `Read-IsalaLatestLogs -ErrorsOnly` en daarna de laatste
relevante context lezen met `Read-IsalaLatestLogs -Tail 300`. Rapporteer:

1. de eerste echte foutmelding;
2. de workflowstap waarin die fout optreedt;
3. eventuele onderliggende Docker-, database- of runtimefout;
4. de concrete herstelactie.

Na deze analyse moet Codex direct de fix in gang zetten: lokaliseer de
betreffende code of workflowconfiguratie, implementeer een veilige gerichte
oplossing en voer daarna passende syntaxchecks, tests of een beperkte
workflowcontrole uit. Rapporteer vervolgens zowel de gevonden oorzaak als de
doorgevoerde fix en het verificatieresultaat. Alleen wanneer de fix
destructief is, externe data kan wijzigen, of de gewenste oplossing meerdere
materieel verschillende richtingen heeft, moet Codex eerst toestemming of
richting vragen.

Lees geen inputafbeeldingen, OCR-tekst of modelartefacten tenzij dat nodig is
voor de foutanalyse. De terminallog kan paden, timestamps en foutdetails
bevatten, maar bevat geen volledige gebruikersdata uit de OCR-crops.
