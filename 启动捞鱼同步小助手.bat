@echo off
cd /d "%~dp0"
if exist "LaoyuSync.exe" (
    start "" "%~dp0LaoyuSync.exe"
    exit /b
)
if exist "dist\LaoyuSync\LaoyuSync.exe" (
    start "" "%~dp0dist\LaoyuSync\LaoyuSync.exe"
    exit /b
)
python core\app.py
if errorlevel 1 pause
