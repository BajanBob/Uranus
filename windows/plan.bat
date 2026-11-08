@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
%PY% -m uranus plan --cycles 2
pause
