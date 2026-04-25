@echo off
setlocal enabledelayedexpansion

REM ---------------------------------------------------------------------------
REM run.bat — download latest app-blocker from GitHub and run it.
REM
REM Save this file anywhere (Desktop is fine), double-click to launch. Each run
REM downloads the latest main branch into %USERPROFILE%\app-blocker, then runs
REM `python main.py` from there.
REM ---------------------------------------------------------------------------

set "INSTALL_DIR=%USERPROFILE%\app-blocker"
set "ZIP_PATH=%TEMP%\app-blocker.zip"
set "EXTRACT_TMP=%TEMP%\app-blocker-extract"
set "ZIP_URL=https://github.com/z3nabi/app-blocker/archive/refs/heads/main.zip"

echo.
echo === app-blocker launcher ===
echo.

echo [1/4] Checking for Python...
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo ERROR: Neither 'python' nor 'py' was found on PATH.
        echo Install Python from python.org, or ask IT to add it.
        pause
        exit /b 1
    )
    set "PY=py"
) else (
    set "PY=python"
)
echo Using: !PY!

echo.
echo [2/4] Downloading latest from GitHub...
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_PATH%' -UseBasicParsing"
if errorlevel 1 (
    echo ERROR: Download failed. Check network or GitHub access.
    pause
    exit /b 1
)

echo.
echo [3/4] Extracting to %INSTALL_DIR%...
if exist "%EXTRACT_TMP%" rmdir /S /Q "%EXTRACT_TMP%"
if exist "%INSTALL_DIR%" rmdir /S /Q "%INSTALL_DIR%"
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_TMP%' -Force"
if errorlevel 1 (
    echo ERROR: Extract failed.
    pause
    exit /b 1
)
move "%EXTRACT_TMP%\app-blocker-main" "%INSTALL_DIR%" >nul
rmdir /S /Q "%EXTRACT_TMP%" 2>nul
del "%ZIP_PATH%" 2>nul

echo.
echo [4/4] Starting app-blocker...
echo (close the app window to exit)
echo.
cd /d "%INSTALL_DIR%"
!PY! main.py

echo.
echo app-blocker exited.
pause
