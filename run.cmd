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

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\automation\powershell\watch-webui.ps1" -QuietSeconds 30
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo De automatische WebUI-updater is gestopt met code %RESULT%.
  pause
)
exit /b %RESULT%
