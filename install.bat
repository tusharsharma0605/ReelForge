@echo off
setlocal
cd /d "%~dp0"
title ReelForge setup
echo ==============================
echo   ReelForge setup
echo ==============================
echo.

set "PY="
where py >nul 2>nul && py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=py -3"
if not defined PY (
  where python >nul 2>nul && python -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.10 or newer was not found.
  echo Install it from https://www.python.org/downloads/
  echo IMPORTANT: tick "Add python.exe to PATH" in the installer, then run install.bat again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment in .venv ...
  %PY% -m venv .venv || goto :fail
)

echo Installing components (first time takes a few minutes, about 300 MB)...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail

echo Creating the Desktop shortcut...
".venv\Scripts\python.exe" make_shortcut.py

echo.
echo Done! Double-click "ReelForge" on your Desktop (or ReelForge.bat in this folder) to start.
pause
exit /b 0

:fail
echo.
echo Setup failed. Check your internet connection and run install.bat again.
pause
exit /b 1
