URANUS ON WINDOWS
=================

EASIEST: download Uranus-Windows-exe.zip, unzip it and double-click Uranus.exe.
No Python needed. The buttons are numbered: 1. Edit settings, 2. Show plan,
3. Dry run, then ON AIR. WhisperMite-Setup.exe is in the WhisperMite folder.

FROM SOURCE (needs Python):

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Double-click windows\install.bat  (installs numpy, scipy, sounddevice, pyserial
   and runs the 17 self-tests).
3. Edit config\uranus.toml in Notepad: callsign, grid, lat/lon, wspr_power_dbm.
4. Double-click windows\plan.bat to see the transmit timeline.
5. Double-click windows\pumpkin-demo.bat to watch the Pumpkin mode decode at -29 dB.

GOING ON AIR
- Install WSJT-X (provides ft8code.exe and wsprcode.exe for FT8/WSPR).
  Uranus looks in C:\WSJT\wsjtx\bin automatically; otherwise set the
  environment variable WSJTX_BIN to WSJT-X's bin folder.
- Install Hamlib for Windows and add its bin folder to PATH.
- Edit and run windows\start-rigctld.bat (rig model number + COM port).
- Run windows\list-audio-devices.bat and put your rig's USB audio output
  in audio_device in config\uranus.toml.
- In config\uranus.toml set  backend = "hamlib".
- Make sure Windows time is accurate to well under 1 second
  (Settings > Time & language > Sync now; better: install Meinberg NTP).
  FT8, WSPR and Pumpkin will not decode with a wrong clock.
- Double-click windows\run-on-air.bat.

Pumpkin needs a GPS-disciplined oscillator at BOTH stations (see docs\PUMPKIN-MODE.md).
Check your licence before enabling APRS frequencies outside Region 2,
unattended operation, or the new UR/Pumpkin modes.

WhisperMite tools are in the WhisperMite folder of the Windows zip:
double-click WhisperMite\WhisperMite-Setup.bat for the settings uploader.
