URANUS ON WINDOWS
=================

EASIEST: download Uranus-Windows-exe.zip, unzip it and double-click Uranus.exe.
No Python needed. On first start the Setup wizard asks for your callsign,
grid, radio (e.g. Icom IC-9100), its USB Audio CODEC, CAT port, bands and
PSK Reporter. Then press Show plan, Dry run, and ON AIR. Hover over any
control for help. WhisperMite-Setup.exe is in the WhisperMite folder.

FROM SOURCE (needs Python):

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Double-click windows\install.bat  (installs numpy, scipy, sounddevice, pyserial
   and runs the 17 self-tests).
3. Edit config\uranus.toml in Notepad: callsign, grid, lat/lon, wspr_power_dbm.
4. Double-click windows\plan.bat to see the transmit timeline.
5. Double-click windows\pumpkin-demo.bat to watch the Pumpkin mode decode at -29 dB.

GOING ON AIR (plug and play)
- Switch the radio on and plug in its USB cable (Icom: install Icom's USB driver once).
- Run the Setup wizard and choose your radio, e.g. Icom IC-9100. The COM port,
  CAT speed, Hamlib model and the radio's USB Audio CODEC are filled in for you.
- Press Test radio. Uranus starts its built-in Hamlib (the hamlib folder next to
  Uranus.exe) by itself and shows the radio's frequency. Nothing to install.
- Install WSJT-X if you want FT8/WSPR slots (Uranus uses its ft8code/wsprcode).
- Make sure Windows time is accurate to well under 1 second
  (Settings > Time & language > Sync now; better: install Meinberg NTP).
- Bands and modes: tick or untick each band, mode and frequency.
- Press Show plan, Dry run, then ON AIR.
- Listen + decode: choose Pumpkin, Cucumber or UR in the Receiver panel. The
  panel shows the slot countdown, "Decoding...", and each slot's result; the
  waterfall shows the radio's audio; every station heard scrolls along the
  bottom (HEARD) with a beep and flash.
- Keep the hamlib folder next to Uranus.exe. Close WSJT-X, RS-BA1 or any other
  program using the radio's COM port first: only one program can use it.

Pumpkin needs a GPS-disciplined oscillator at BOTH stations (see docs\PUMPKIN-MODE.md).
Check your licence before enabling APRS frequencies outside Region 2,
unattended operation, or the new UR/Pumpkin modes.

WhisperMite tools are in the WhisperMite folder of the Windows zip:
double-click WhisperMite\WhisperMite-Setup.bat for the settings uploader.
