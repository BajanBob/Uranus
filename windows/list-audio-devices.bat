@echo off
cd /d "%~dp0.."
set PY=py -3
where py >nul 2>nul || set PY=python
echo Copy the name or number of your rig's USB audio OUTPUT into audio_device in config\uranus.toml
%PY% -c "import sounddevice; print(sounddevice.query_devices())"
pause
