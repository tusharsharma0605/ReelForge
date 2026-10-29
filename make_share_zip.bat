@echo off
rem Builds ReelForge-share.zip with only the app files: no API keys, no videos/uploads, no .venv.
cd /d "%~dp0"
set "STAGE=%TEMP%\ReelForge-share"
if exist "%STAGE%" rmdir /s /q "%STAGE%"
robocopy . "%STAGE%\ReelForge" /E /XD .venv data __pycache__ .git /XF ReelForge-share.zip *.pyc >nul
if exist ReelForge-share.zip del ReelForge-share.zip
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\ReelForge' -DestinationPath 'ReelForge-share.zip'"
rmdir /s /q "%STAGE%"
echo Created ReelForge-share.zip - safe to share (contains no keys or personal videos).
pause
