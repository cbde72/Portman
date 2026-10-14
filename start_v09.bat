@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv --system-site-packages .venv
)
".venv\Scripts\python.exe" tools\prepare_environment.py
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" src\Gui\PortMan_V09.py
