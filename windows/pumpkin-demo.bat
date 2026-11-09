@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
echo Pumpkin coherent mode: encode, add noise at -29 dB, decode.
%PY% -m uranus pumpkin-loopback --submode PUMPKIN-60 --snr -29
%PY% -m uranus link-budget --example
pause
