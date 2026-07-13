@echo off
REM ==========================================================================
REM  Station Manager - double-click launcher for Windows
REM  Just double-click this file. The first run sets everything up (a minute
REM  or two); after that it opens instantly in your web browser.
REM ==========================================================================
cd /d "%~dp0"
title Station Manager

echo ============================================
echo    Station Manager - starting up...
echo ============================================
echo.

REM --- 1) Find Python 3 -------------------------------------------------------
call :find_python
if defined PY goto :have_python

REM --- 2) Not found: try to install it automatically via winget --------------
echo Python was not found. Trying to install it for you automatically...
echo (You may see a Windows dialog - please click Yes / Allow if it appears.)
echo.
where winget >nul 2>&1
if %errorlevel%==0 (
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  REM Refresh this window's PATH so the new python is visible.
  for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "PATH=%%B;%PATH%"
  call :find_python
)
if defined PY goto :have_python

echo.
echo   Automatic install did not work on this PC.
echo   Please install Python once, by hand:
echo     1. Go to  https://www.python.org/downloads/
echo     2. Download and run the installer.
echo     3. IMPORTANT: tick the box "Add Python to PATH".
echo     4. Then double-click this file again.
echo.
pause
exit /b 1

:have_python
REM --- 3) First-time setup: private environment + the two libraries ----------
if not exist ".venv" (
  echo First-time setup ^(this happens only once, please wait^)...
  %PY% -m venv .venv || ( echo Setup failed. & pause & exit /b 1 )
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
  echo Setup complete.
  echo.
)

REM --- 4) Launch (app.py opens your browser automatically) -------------------
echo Station Manager is running. Your browser will open in a moment.
echo Keep THIS window open while you use the app. Close it to stop.
echo.
".venv\Scripts\python.exe" app.py
pause
exit /b 0

:find_python
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
goto :eof
