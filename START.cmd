@echo off
setlocal
cd /d "%~dp0"

echo Updating IsalaOCR from Git...
where git >nul 2>&1
if errorlevel 1 (
    echo Git is not available in PATH. Startup aborted.
    pause
    exit /b 1
)

git pull --ff-only
if errorlevel 1 (
    echo.
    echo Git pull failed. Startup aborted to avoid running stale code.
    pause
    exit /b 1
)

echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File ".\automation\powershell\launcher.ps1" %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
