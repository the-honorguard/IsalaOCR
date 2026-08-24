@echo off
setlocal
cd /d "%~dp0"

echo IsalaOCR starten met automatische WebUI-updates...
call ".\START.cmd"
if errorlevel 1 (
  echo Startup mislukt.
  exit /b %ERRORLEVEL%
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\automation\powershell\watch-webui.ps1"
set "RESULT=%ERRORLEVEL%"
exit /b %RESULT%
