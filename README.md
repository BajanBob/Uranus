# Uranus

A Raspberry Pi beacon sequencer for **2 m and 70 cm**. It sends APRS, FT8,
WSPR and an experimental new weak-signal mode called **UR**. It runs on its
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

## Hardware

* **Raspberry Pi** running NTP. Accurate time is essential for FT8, WSPR and UR.
* **An all-mode 2 m / 70 cm rig with CAT and a USB sound card**, for example
  an IC-9700, IC-705 or FT-991A. FT8, WSPR and UR need USB (SSB) mode; APRS
  uses FM.
* **For UR on 70 cm,** a GPSDO or TCXO-stable rig is strongly recommended.
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

### UR mode tools

```bash
python3 -m uranus ur-encode "8P6AB GK03 1 1234" ur.wav --submode UR-60
python3 -m uranus ur-decode ur.wav --submode UR-60 [--expect 8P6AB GK03]
python3 -m uranus ur-loopback --submode UR-15 --snr -19
python3 -m uranus ur-sim                    # sensitivity table
```

The decoder takes any WAV recorded from a USB receiver with the dial on the
beacon frequency.

## Sensitivity summary (measured, 50 % decode, 2500 Hz)

| | Single frame | 4 repeats stacked | WSJT-X equivalent |
|---|---|---|---|
| UR-15 | −20.0 | −23.4 | FST4-15 −20.7 / FT8 ≈ −21 |
| UR-60 | −26.0 | −29.5 | FST4-60 −28.1 |
| UR-120 | −29.0 | −32.5 | FST4W-120 −32.8 |

UR v0.1 is a working, measured **research baseline**, not yet better than
WSJT-X. See [docs/UR-MODE.md](docs/UR-MODE.md) and
[docs/RESEARCH.md](docs/RESEARCH.md) for why, and for the roadmap to close
the gap.

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
