@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

%PYTHON% ".\src\gequhai_downloader.py" ".\input\songs.csv" -o ".\downloads"
pause
