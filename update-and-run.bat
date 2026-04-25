@echo off
setlocal enabledelayedexpansion

REM ---------------------------------------------------------------------------
REM update-and-run.bat - pull latest app-blocker from GitHub and run it.
REM
REM This script's job is to keep you on the latest code. If the download
REM fails, it errors out loudly rather than silently running stale code.
REM
REM Order of acquisition:
REM   1. If a manually-downloaded zip exists at %USERPROFILE%\Downloads\
REM      app-blocker-main.zip, use it (then delete it).
REM   2. Otherwise try BITS, WebClient, IWR, curl in that order. Each takes
REM      a different path through Windows networking - one usually gets
REM      through corp proxies that require NTLM/Negotiate auth.
REM   3. If all fail: error out, open the URL in browser, and tell the user
REM      where to drop the zip for next run.
REM
REM To run the last installed version WITHOUT updating, just run:
REM   python "%USERPROFILE%\app-blocker\main.py"
REM ---------------------------------------------------------------------------

set "INSTALL_DIR=%USERPROFILE%\app-blocker"
set "ZIP_PATH=%TEMP%\app-blocker.zip"
set "EXTRACT_TMP=%TEMP%\app-blocker-extract"
set "DOWNLOADS_ZIP=%USERPROFILE%\Downloads\app-blocker-main.zip"
set "ZIP_URL=https://github.com/z3nabi/app-blocker/archive/refs/heads/main.zip"
set "UA=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

echo.
echo === app-blocker launcher ===
echo.

echo [1/4] Checking for Python...
set "PY="
where python >nul 2>&1 && set "PY=python"
if "!PY!"=="" (where py >nul 2>&1 && set "PY=py")
if "!PY!"=="" (
    echo ERROR: Neither 'python' nor 'py' was found on PATH.
    pause & exit /b 1
)
echo   using: !PY!

echo.
echo [2/4] Acquiring source...

REM Use a manually-downloaded zip from Downloads if present
if exist "%DOWNLOADS_ZIP%" (
    echo   found manual download at %DOWNLOADS_ZIP%
    copy /Y "%DOWNLOADS_ZIP%" "%ZIP_PATH%" >nul
    del "%DOWNLOADS_ZIP%" >nul 2>&1
    goto :extract
)

if exist "%ZIP_PATH%" del "%ZIP_PATH%" >nul 2>&1

REM Method 1: BITS - uses WinHTTP, often handles corp proxy auth transparently
echo   trying BITS...
powershell -NoProfile -Command "try { Start-BitsTransfer -Source '%ZIP_URL%' -Destination '%ZIP_PATH%' -ErrorAction Stop } catch { exit 1 }" 2>nul
if not errorlevel 1 if exist "%ZIP_PATH%" (echo   ok ^(BITS^) & goto :extract)

REM Method 2: System.Net.WebClient with explicit system proxy + default creds
echo   trying WebClient with system proxy...
powershell -NoProfile -Command "try { $wc = New-Object System.Net.WebClient; $proxy = [System.Net.WebRequest]::GetSystemWebProxy(); $proxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials; $wc.Proxy = $proxy; $wc.Headers.Add('User-Agent', '%UA%'); $wc.DownloadFile('%ZIP_URL%', '%ZIP_PATH%') } catch { exit 1 }" 2>nul
if not errorlevel 1 if exist "%ZIP_PATH%" (echo   ok ^(WebClient^) & goto :extract)

REM Method 3: Invoke-WebRequest with explicit system proxy + default creds
echo   trying Invoke-WebRequest with system proxy...
powershell -NoProfile -Command "try { [System.Net.WebRequest]::DefaultWebProxy = [System.Net.WebRequest]::GetSystemWebProxy(); [System.Net.WebRequest]::DefaultWebProxy.Credentials = [System.Net.CredentialCache]::DefaultNetworkCredentials; Invoke-WebRequest -Uri '%ZIP_URL%' -OutFile '%ZIP_PATH%' -UseBasicParsing -UserAgent '%UA%' -UseDefaultCredentials } catch { exit 1 }" 2>nul
if not errorlevel 1 if exist "%ZIP_PATH%" (echo   ok ^(IWR^) & goto :extract)

REM Method 4: curl.exe with proxy auth negotiation
where curl.exe >nul 2>&1
if not errorlevel 1 (
    echo   trying curl --proxy-negotiate...
    curl.exe -fsSL --proxy-negotiate -u : -A "%UA%" -o "%ZIP_PATH%" "%ZIP_URL%" 2>nul
    if not errorlevel 1 if exist "%ZIP_PATH%" (echo   ok ^(curl/negotiate^) & goto :extract)
    echo   trying curl --proxy-ntlm...
    curl.exe -fsSL --proxy-ntlm -u : -A "%UA%" -o "%ZIP_PATH%" "%ZIP_URL%" 2>nul
    if not errorlevel 1 if exist "%ZIP_PATH%" (echo   ok ^(curl/ntlm^) & goto :extract)
)

REM All auto methods failed - error loudly. Do NOT silently run stale code.
echo.
echo ERROR: Could not download latest from GitHub.
echo The corp proxy denied the request.
echo.
echo TRY:
echo   - Open https://github.com/z3nabi/app-blocker in your browser first to
echo     authenticate to the proxy, then re-run this script.
echo   - Or download the zip manually: %ZIP_URL%
echo     Save to %USERPROFILE%\Downloads\app-blocker-main.zip and re-run.
echo.
if exist "%INSTALL_DIR%\main.py" (
    echo To run the LAST INSTALLED version without updating:
    echo   cd /d "%INSTALL_DIR%"
    echo   !PY! main.py
    echo.
)
start "" "%ZIP_URL%"
pause
exit /b 1

:extract
echo.
echo [3/4] Extracting to %INSTALL_DIR%...
if exist "%EXTRACT_TMP%" rmdir /S /Q "%EXTRACT_TMP%"
if exist "%INSTALL_DIR%" rmdir /S /Q "%INSTALL_DIR%"
powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_TMP%' -Force"
if errorlevel 1 (
    echo   extract failed.
    pause & exit /b 1
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
