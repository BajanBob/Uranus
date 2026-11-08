@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
echo Installing Uranus requirements (numpy, scipy, sounddevice, pyserial)...
%PY% --version || (echo Python 3.11+ is required: https://www.python.org/downloads/  - tick "Add to PATH" & pause & exit /b 1)
%PY% -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)" || (echo Python 3.11 or newer is required. & pause & exit /b 1)
%PY% -m pip install --upgrade numpy scipy sounddevice pyserial
echo.
echo Running self-tests...
%PY% -m unittest tests.test_uranus
echo.
echo Done. Next: edit config\uranus.toml (callsign, grid, position), then run windows\plan.bat
pause
