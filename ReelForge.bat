@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" call install.bat
start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.pyw"
