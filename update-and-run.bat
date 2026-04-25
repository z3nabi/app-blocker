@echo off
REM Thin wrapper around update_and_run.py — keeps a console open and
REM forwards exit codes. Save this file alongside update_and_run.py
REM (e.g. both on your Desktop). Each launch downloads the latest
REM code and runs it.

setlocal

set "PY="
where python >nul 2>&1 && set "PY=python"
if "%PY%"=="" (where py >nul 2>&1 && set "PY=py")
if "%PY%"=="" (
    echo ERROR: neither 'python' nor 'py' on PATH.
    pause
    exit /b 1
)

set "SCRIPT=%~dp0update_and_run.py"
if not exist "%SCRIPT%" (
    echo ERROR: update_and_run.py not found next to this .bat.
    echo   Expected: %SCRIPT%
    echo   Download from: https://raw.githubusercontent.com/z3nabi/app-blocker/main/update_and_run.py
    pause
    exit /b 1
)

%PY% "%SCRIPT%"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%
