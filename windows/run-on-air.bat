@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
echo ON AIR. Make sure rigctld is running (start-rigctld.bat) and backend = "hamlib" in config\uranus.toml
echo Press Ctrl+C to stop.
%PY% -m uranus run
pause
