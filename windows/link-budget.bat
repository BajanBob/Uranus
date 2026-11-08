@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
%PY% -m uranus link-budget --watts 10 --mhz 144.49 --km 200 --extra-loss 25 --tx-gain 10 --rx-gain 13
pause
