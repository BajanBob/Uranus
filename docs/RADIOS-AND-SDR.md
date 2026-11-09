# Radios, SDRs and the 1.25 m band

Uranus works with three kinds of equipment. Pick yours in **Station setup**
(button 0 in the Uranus window); every control there explains itself when
you hover over it.

| Equipment | Bands | Transmit | USB audio | Uranus backend |
|---|---|---|---|---|
| Generic CAT rig with USB audio | 2 m, 70 cm | SSB + FM | built-in | hamlib |
| Icom IC-9700 | 2 m, 70 cm | SSB + FM | built-in | hamlib |
| Icom IC-705 | 2 m, 70 cm | SSB + FM | built-in | hamlib |
| Icom IC-905 | 2 m, 70 cm | SSB + FM | built-in | hamlib |
| Yaesu FT-991A | 2 m, 70 cm | SSB + FM | built-in | hamlib |
| Yaesu FT-818ND | 2 m, 70 cm | SSB + FM | external interface | hamlib |
| Kenwood TS-2000 | 2 m, 70 cm | SSB + FM | external interface | hamlib |
| Kenwood TH-D75A (US) | 2 m, 1.25 m, 70 cm | FM only | external interface | audio-only |
| Kenwood TH-D74A (US) | 2 m, 1.25 m, 70 cm | FM only | external interface | audio-only |
| Yaesu VX-6R / VX-7R (US) | 2 m, 1.25 m, 70 cm | FM only | external interface | audio-only |
| Alinco DR-235T | 1.25 m | FM only | external interface | audio-only |
| AnyTone AT-D578UV III Plus (220 version) | 2 m, 1.25 m, 70 cm | FM only | external interface | audio-only |
| BTECH UV-5X3 | 2 m, 1.25 m, 70 cm | FM only | external interface | audio-only |
| 222 MHz transverter + all-mode IF rig | 1.25 m | SSB + FM | built-in | hamlib |
| HackRF One (SDR transmit, experimental) | 2 m, 1.25 m, 70 cm | SSB + FM | n/a | hackrf |
| RTL-SDR v3 / v4 (receive only) | 2 m, 1.25 m, 70 cm | Receive only | n/a | rtl_fm |
| ADALM-Pluto (SDR) | 70 cm | SSB + FM | n/a | audio-only |
| SDRplay RSP1B / RSPdx (receive) | 2 m, 1.25 m, 70 cm | Receive only | n/a | audio-only |
| Airspy R2 / Mini (receive) | 2 m, 1.25 m, 70 cm | Receive only | n/a | audio-only |

*FM only* radios can send APRS but not the SSB weak-signal modes (FT8,
WSPR, UR, Pumpkin). Specifications vary by model year and regional version, so
always check the radio's manual. To add a radio, add a `Profile` to
`uranus/radios.py`.

## 1.25 m (220 MHz)

* **Allocation:** ITU Region 2 only. Barbados allocates 222-225 MHz; confirm
  on your licence.
* **Where Uranus transmits:** weak-signal work sits in 222.000-222.150 MHz,
  with 222.100 MHz as the SSB/CW calling frequency. The beacon uses 222.130 MHz,
  clear of the calling frequency.
* **Equipment:** few all-mode rigs cover the band. For SSB modes use a 222 MHz
  transverter with an IF rig (set `transverter_lo_mhz`: 194 for a 28 MHz IF,
  78 for a 144 MHz IF) or the HackRF backend. Tri-band FM radios cover APRS.
* **Map and propagation:** the band is drawn in rose on the station map. The
  propagation analyst treats it like 2 m for ducting, with sporadic-E and
  TEP far less likely.

## SDR

### Receive

* **RTL-SDR:** set `[receive] source = "rtl_fm"` and Uranus records USB audio
  straight from the dongle with `rtl_fm` (install the `rtl-sdr` tools). Set
  `rtl_ppm` for your dongle's frequency error. Pumpkin needs the frequency within
  about 0.6 Hz (PUMPKIN-60), so use a TCXO or GPS-locked SDR for Pumpkin.
* **SDRplay, Airspy, Pluto and others:** run their own software in USB mode and
  send the audio to Uranus through a virtual audio cable, choosing that cable
  as "Audio from radio".

### Transmit (experimental)

* **HackRF One:** set `backend = "hackrf"`. Uranus streams 8-bit I/Q to
  `hackrf_transfer`: USB for FT8, WSPR, UR and Pumpkin, FM (3 kHz deviation) for
  APRS. The carrier sits 200 kHz from the HackRF's centre frequency so its
  DC leak stays outside the signal. In testing, the unwanted lower sideband
  was suppressed and everything else was 65 dB down.
* **You must filter it.** A HackRF puts out milliwatts with strong harmonics.
  On air it must be followed by a band-pass filter for the band in use,
  normally with an amplifier. Start at a low `hackrf_txvga` and measure.
* **Neither path has been tested on real hardware yet.** Reports are welcome.
