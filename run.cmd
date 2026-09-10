@echo off
setlocal
cd /d "%~dp0"

echo IsalaOCR starten met automatische WebUI-updates...
call ".\START.cmd"
if errorlevel 1 (
  echo Startup mislukt.
  pause
  exit /b 1
)

echo.
echo ================================================================
echo IsalaOCR WebUI-watcher wordt gestart.
echo Codewijzigingen worden na 60 seconden stilte automatisch gebouwd.
echo De watcher blijft actief; stoppen met Ctrl+C.
echo ================================================================
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\automation\powershell\watch-webui.ps1" -QuietSeconds 60
set "RESULT=%ERRORLEVEL%"
echo.
echo De automatische WebUI-updater is gestopt met code %RESULT%.
pause
exit /b %RESULT%
