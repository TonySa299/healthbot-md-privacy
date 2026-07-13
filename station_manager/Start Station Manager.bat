@echo off
REM ==========================================================================
REM  Station Manager - double-click launcher for Windows
REM  Just double-click this file. On first run it sets itself up (one minute),
REM  after that it starts instantly and opens in your web browser.
REM ==========================================================================
cd /d "%~dp0"
title Station Manager

echo Starting Station Manager...

REM Find a Python 3 interpreter (the "py" launcher, or python on PATH).
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo   Python 3 is not installed on this PC.
  echo   Please install it from https://www.python.org/downloads/
  echo   During install, TICK the box "Add Python to PATH", then try again.
  echo.
  pause
  exit /b 1
)

REM Create a private environment and install the two libraries the first time.
if not exist ".venv" (
  echo First-time setup ^(this happens only once^)...
  %PY% -m venv .venv || ( echo Setup failed. & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

REM Launch. app.py opens your browser automatically.
".venv\Scripts\python.exe" app.py
pause
