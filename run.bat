@echo off
setlocal enabledelayedexpansion

REM ---------------------------------------------------------------------------
REM run.bat - download latest app-blocker from GitHub and run it.
REM
REM Save anywhere (Desktop is fine), double-click to launch.
REM ---------------------------------------------------------------------------

set "INSTALL_DIR=%USERPROFILE%\app-blocker"
set "ZIP_PATH=%TEMP%\app-blocker.zip"
set "EXTRACT_TMP=%TEMP%\app-blocker-extract"
set "ZIP_URL=https://github.com/z3nabi/app-blocker/archive/refs/heads/main.zip"
set "UA=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

echo.
echo === app-blocker launcher ===
echo.

echo [1/4] Checking for Python...
set "PY="
where python >nul 2>&1 && set "PY=python"
if "!PY!"=="" (
    where py >nul 2>&1 && set "PY=py"
)
if "!PY!"=="" (
    echo ERROR: Neither 'python' nor 'py' was found on PATH.
    pause
    exit /b 1
)
echo Using: !PY!

echo.
echo [2/4] Downloading from GitHub...
if exist "%ZIP_PATH%" del "%ZIP_PATH%" >nul 2>&1

REM Try curl.exe first (built into Win10+, often handles corp proxies well)
where curl.exe >nul 2>&1
if not errorlevel 1 (
    echo   trying curl.exe...
    curl.exe -fsSL -A "%UA%" --proxy-anyauth -o "%ZIP_PATH%" "%ZIP_URL%" 2>nul
    if not errorlevel 1 if exist "%ZIP_PATH%" goto :downloaded
    echo   curl.exe failed, trying PowerShell...
)

REM Fallback: PowerShell with default credentials + browser UA
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; try { [System.Net.WebRequest]::DefaultWebProxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials } catch {}; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_PATH%' -UseBasicParsing -UserAgent '%UA%' -UseDefaultCredentials"
if errorlevel 1 goto :download_failed
if not exist "%ZIP_PATH%" goto :download_failed
goto :downloaded

:download_failed
echo.
echo ERROR: All download methods failed.
echo.
echo Workaround: download this URL manually in your browser:
echo   %ZIP_URL%
echo Save it as:
echo   %ZIP_PATH%
echo Then re-run this script.
echo.
pause
exit /b 1

:downloaded
echo   downloaded to %ZIP_PATH%

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
