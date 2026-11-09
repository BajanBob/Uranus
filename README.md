# Uranus

A Raspberry Pi beacon sequencer for **2 m and 70 cm**. It sends APRS, FT8,
WSPR and two new weak-signal modes: **UR** (noncoherent) and **URC**
(coherent, with pilot-aided carrier recovery). **URC beats WSJT-X FST4 by
2.7–4 dB at the same slot length and peak power**, provided both stations
use a GPSDO. It runs on its
own: it switches frequency and mode through CAT control and keeps the gaps
you set.

## Default sequence

```
2 m:   APRS 144.390 → 1 min → FT8 144.174 → 1 min → WSPR 144.490
         → 3 min →
70 cm: FT8 432.174 → 1 min → WSPR 432.300
         → 3 min → repeat
```

Every frequency you asked for is in `config/uranus.toml`. APRS 145.570,
144.800, 144.930 and 432.800 are **disabled by default**, because they are
not Region-2 APRS channels. Turn them on only if your licence and band plan
allow it. FT8 waits for the next 15 s boundary, WSPR for the next even minute
and UR for its period, so some gaps run a little longer than 1 minute.

Run `python -m uranus plan` to see the exact timeline.

**Windows:** download `Uranus-Windows-exe.zip` from the latest Release or Actions build and double-click `Uranus.exe` (no Python needed). From source: download the Windows zip or see [windows/README-WINDOWS.txt](windows/README-WINDOWS.txt); double-click `windows\install.bat`.

## Hardware

* **Raspberry Pi** running NTP. Accurate time is essential for FT8, WSPR and UR.
* **An all-mode 2 m / 70 cm rig with CAT and a USB sound card**, for example
  an IC-9700, IC-705 or FT-991A. FT8, WSPR and UR need USB (SSB) mode; APRS
  uses FM.
* **For URC, a GPSDO-locked rig at BOTH ends** (frequency within ±0.6 Hz for
  URC-60). UR and the WSJT-X modes work with an ordinary TCXO.
* **Do not use `rpitx`** (Pi GPIO transmit) on 2 m or 70 cm. Its harmonics
  and spurs are far outside the rules.
* **An SDR transmitter** (Pluto, HackRF) is possible later. It needs a proper
  band-pass filter and amplifier and is not implemented yet.

## Install

```bash
sudo apt install python3-numpy python3-scipy alsa-utils libhamlib-utils wsjtx
git clone https://github.com/BajanBob/Uranus && cd Uranus
python3 -m unittest -v tests.test_uranus
```

WSJT-X supplies `ft8code` and `wsprcode`, the reference encoders that Uranus
uses for FT8 and WSPR. Hamlib supplies `rigctld`.

## Use

```bash
nano config/uranus.toml                # set your callsign, grid, position and WSPR power
python3 -m uranus plan                 # show the timeline
python3 -m uranus run --dry-run --once # one cycle writing WAV files to out/, no keying
rigctld -m <rig model> -r /dev/ttyUSB0 -s 19200 &
# then set backend = "hamlib" and audio_device in the config
python3 -m uranus run                  # on air
```

### Listen, station map and PSK Reporter

```bash
python3 -m uranus listen                    # decode URC/UR from the rig every slot, log to out/spots.jsonl
python3 -m uranus map --psk --open          # map: blue = heard in the last 30 min, red = earlier
python3 -m uranus map --demo --open         # the same map with clearly labelled sample stations
```

The map colours stations by band: **2 m in teal, 70 cm in violet**. A
**blue ring** means online (heard in the last 30 minutes) and a **red
ring**, drawn faded, means offline. Each label shows callsign, band, SNR,
bearing and distance. Solid lines mean you decoded them, dashed lines mean
they decoded you (from PSK Reporter), and thick lines mean both. Online it
draws on OpenStreetMap; offline it falls back to a Maidenhead-grid map.

### Propagation analyst

For every contact, Uranus estimates which propagation mode most likely
carried it: line of sight, tropospheric scatter, tropospheric ducting,
aircraft scatter, meteor scatter, sporadic-E or trans-equatorial (TEP). It
gives a confidence and the reasons, plus a per-band summary of what is
happening now. The evidence is the path length, the band, local solar time
at the path midpoint, the season, the path geometry (TEP needs a
north-south path across the geomagnetic equator) and the signal itself.
After each URC decode, the decoder re-encodes the message and measures the
fading depth and Doppler spread against it.

This is an explainable, rule-based estimate, not a trained neural network.
No labelled propagation data exists yet to train one; the spot log Uranus
keeps is the data a learned model could use later.

Set `pskreporter = true` under `[reporting]` to upload your URC/UR decodes
to PSK Reporter (start with its test server, the default). WSPRnet only
accepts WSPR/FST4W, so URC spots are not sent there.

### Downloads

From the latest GitHub Release:

* **Windows:** `Uranus-Windows-exe.zip`. Double-click `Uranus.exe`.
* **Raspberry Pi:** `Uranus-RaspberryPi.zip`. Run `bash linux/install-pi.sh`.
* **Linux:** `Uranus-Linux.zip`. Run `bash linux/install-linux.sh`.

### UR mode tools

```bash
python3 -m uranus ur-encode "8P6AB GK03 1 1234" ur.wav --submode UR-60
python3 -m uranus ur-decode ur.wav --submode UR-60 [--expect 8P6AB GK03]
python3 -m uranus ur-loopback --submode UR-15 --snr -19
python3 -m uranus ur-sim                    # sensitivity table
python3 -m uranus urc-encode "8P6AB GK03 1 1234" urc.wav --submode URC-60
python3 -m uranus urc-decode urc.wav --submode URC-60
python3 -m uranus urc-loopback --submode URC-60 --snr -30
python3 -m uranus link-budget --watts 10 --mhz 144.49 --km 200 --extra-loss 25
```

The decoder takes any WAV recorded from a USB receiver with the dial on the
beacon frequency.

## Sensitivity summary (measured, 50 % decode, SNR in 2500 Hz)

| Slot | UR (noncoherent) | **URC (coherent, GPSDO)** | WSJT-X FST4 |
|---|---|---|---|
| 15 s | −19.4 | **−24.7** | −20.7 |
| 60 s | −25.4 | **−30.8** | −28.1 |
| 120 s | −29.0 (sim) | **−34.1 (sim)** | −31.3 (FST4W −32.8) |

The 15 s and 60 s figures come from the full audio path with blind time and
frequency search; "(sim)" means simulation only. See
[docs/URC-MODE.md](docs/URC-MODE.md), [docs/UR-MODE.md](docs/UR-MODE.md),
[docs/RESEARCH.md](docs/RESEARCH.md) and
[docs/ACHIEVEMENTS.md](docs/ACHIEVEMENTS.md).

## Operating notes

* **APRS:** listen-before-talk is on, using the S-meter through CAT. Keep the
  path short (`WIDE1-1`) and the interval reasonable.
* **FT8:** this mode is designed for two-way contacts. An unattended
  `CQ` beacon that never answers is generally frowned upon; consider dropping
  FT8 from the sequence or staying at the station.
* **Unattended operation:** automatic control of a beacon station has
  licence conditions. Check what Barbados requires before running it
  unattended.
* **WSPR power:** `wspr_power_dbm` must be your real output power.

## Licence and testers

Uranus is free software under the **GNU General Public License v3.0** (see
`LICENSE`), the same licence WSJT-X uses. You may use, study, share and
improve it; anything built from it must stay open under the same terms and
keep the credit.

**Testers wanted worldwide.** Run URC-60 alongside FST4W-120 or Q65-60A on
the same path, then open an issue with your callsign, grid, path, the decode
SNR of each mode and any recordings.

Project lead: Kammie Holder, 8P5AB, Barbados.
