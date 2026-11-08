@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
echo One full cycle in real time, writing WAV files to the out folder (no transmitting).
%PY% -m uranus run --dry-run --once
pause
