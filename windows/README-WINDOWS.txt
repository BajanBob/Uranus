URANUS ON WINDOWS
=================

EASIEST: download Uranus-Windows-exe.zip, unzip it and double-click Uranus.exe.
No Python needed. On first start the Setup wizard asks for your callsign,
grid, radio (e.g. Icom IC-9100), its USB Audio CODEC, CAT port, bands and
PSK Reporter. Then tick bands in Bands and modes and press ON AIR. Hover over any
control for help. WhisperMite-Setup.exe is in the WhisperMite folder.

FROM SOURCE (needs Python):

1. Install Python 3.11 or newer from python.org (tick "Add python.exe to PATH").
2. Double-click windows\install.bat  (installs numpy, scipy, sounddevice, pyserial
   and runs the 17 self-tests).
3. Edit config\uranus.toml in Notepad: callsign, grid, lat/lon, wspr_power_dbm.
4. Double-click windows\plan.bat to see the transmit timeline.
5. Double-click windows\pumpkin-demo.bat to watch the Pumpkin mode decode at -29 dB.

SETTINGS
Uranus.exe keeps your settings in %APPDATA%\Uranus\uranus.toml (your Windows
profile), so they survive when you unzip a new version into a new folder. The
first time a new version starts, it brings your settings over from an older
Uranus folder automatically.

GOING ON AIR (plug and play)
- Switch the radio on and plug in its USB cable (Icom: install Icom's USB driver once).
- Run the Setup wizard and choose your radio, e.g. Icom IC-9100. The COM port,
  CAT speed, Hamlib model and the radio's USB Audio CODEC are filled in for you.
- Press Test radio. Uranus starts its built-in Hamlib (the hamlib folder next to
  Uranus.exe) by itself and shows the radio's frequency. Nothing to install.
- Install WSJT-X if you want FT8/WSPR slots (Uranus uses its ft8code/wsprcode).
- Make sure Windows time is accurate to well under 1 second
  (Settings > Time & language > Sync now; better: install Meinberg NTP).
- Bands and modes: one tab per band; tick each mode on or off and pick its
  frequency from the band-plan list (see docs\FREQUENCIES.md).
- Tick bands in Bands and modes, then press ON AIR. While ON AIR, Uranus decodes on each
  frequency in the gaps between its own transmissions (like WSJT-X).
- Listen + decode: choose AUTO, FT8, FT4, WSPR, APRS, Pumpkin, Cucumber or UR in the
  Receiver panel. FT8, FT4 and WSPR use WSJT-X's own decoders (install WSJT-X;
  close it while Uranus uses the radio). APRS uses Uranus's built-in decoder. The
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

HOW TO TRANSMIT (v0.15.0)
-------------------------
1. Bands and modes: open a band's tab (e.g. 20 m), tick "Use this band", tick the modes to send
   (e.g. FT8), check the frequency, then Save.
2. Optional: Demos and tools -> Show plan (the schedule) and Dry run (one cycle, WAV files only).
3. Station setup: "Transmit with" = hamlib. Use Test transmit once - it reports the measured SWR.
4. ON AIR. The status light is RED "TRANSMITTING" while the PTT is keyed and LILAC "LISTENING"
   while it decodes between transmissions. Stop ends the session after the current transmission.

SWR protection: while transmitting, Uranus reads the radio's SWR meter twice a second. If it goes
above the limit (Station setup -> "Stop transmitting if SWR above", default 2.0) the PTT is dropped
at once, an alert is shown, and that band is not used again until you press ON AIR again.

MAP (v0.16.0): the station map now uses CARTO map tiles (OpenStreetMap data). OpenStreetMap's own
tile servers block maps opened from a file on your PC ("Access blocked ... tile usage policy").

TIMETABLE (v0.18.0): main window -> Timetable. Clock times for ON AIR, for example:
  01:00-06:00  transmit every 3 min (20 an hour), decoding in between
  07:00-09:00  listen and decode
  09:03-22:00  transmit every 3 min (09:03, 09:06, 09:09 ...)
  22:00-23:59  listen and decode
  other times  listen and decode (or pause)
Click "Load my example", tick "Use this timetable", Save, then ON AIR. Transmissions cycle through the
bands and modes ticked in Bands and modes. Listen windows use the Decode and Dial boxes.
Timing is NTP-corrected: Uranus asks internet time servers (pool.ntp.org, time.windows.com) how far the
PC clock is off and corrects for it. The clock at the top shows "NTP ✓" and the next transmission time.
HF bands (160-6 m) can be ticked in Station setup as well as in Bands and modes.
