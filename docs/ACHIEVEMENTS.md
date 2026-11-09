# Uranus — summary of achievements (November 2026)

Project lead: Kammie Holder, 8P5AB, Barbados. Licence: GPL-3.0.

Uranus is a Raspberry Pi beacon system for the 2 m and 70 cm amateur bands.
It sequences APRS, FT8 and WSPR automatically and adds two new weak-signal
modes. One of them, **URC**, decodes 2.7–4 dB below WSJT-X's FST4 at the same
slot length and transmitter peak power.

## 1. What was built

| Component | What it does | Status |
|---|---|---|
| Band/mode sequencer | All of 2 m (APRS → FT8 → WSPR → UR/URC), 3 min pause, then 70 cm; 1 min between transmissions; FT8/WSPR/UR slot alignment | Built, tested |
| Radio control | Hamlib `rigctld` CAT + USB-audio playback; PTT watchdog; maximum TX time; dry-run mode | Built, dry-run tested |
| Spectrum awareness | Listen-before-talk on APRS via the S-meter (the cognitive-radio piece that matters for a beacon) | Built |
| APRS | AX.25 UI frames, AFSK 1200, verified FCS and self-decoding | Built, tested |
| FT8 / WSPR | Audio from WSJT-X's reference encoders, with a Costas sync check | Built; needs `wsjtx` installed |
| **UR mode** | Noncoherent 4-GFSK, K=9 r=⅓ code, soft Viterbi, a-priori decoding, repeat stacking | Built, measured |
| **URC mode** | Coherent MSK + pilots, Kalman/RTS carrier recovery, soft Viterbi | Built, measured |
| Link-budget tool | P/N0 budget with the margin for every mode | Built, tested |
| Simulators | Monte-Carlo threshold measurement, ideal-sync and full audio | Built |
| Tests | 17 automated tests (FEC, packing, loopbacks, no false decodes, APRS, scheduler, link budget) | All pass |

## 2. Where Uranus stands in low-SNR detection

All figures are 50 % decode thresholds, SNR in a 2500 Hz reference
bandwidth (the WSJT-X convention).

| Slot length | Uranus URC (coherent) | Uranus UR (noncoherent) | WSJT-X FST4 | WSJT-X other |
|---|---|---|---|---|
| ~15 s | **−24.7** | −19.4 | −20.7 | FT8 ≈ −21 |
| ~60 s | **−30.8** | −25.4 | −28.1 | — |
| ~120 s | **−34.1** (sim) | −29.0 (sim) | −31.3 | FST4W −32.8, WSPR −31.4 |
| ~300 s | **−38.1** (sim) | −33.0 (sim) | −35.3 | FST4W −36.8 |

Figures without "(sim)" are from the full audio path with blind time and
frequency search. "(sim)" figures are symbol-level simulations; the measured
ones landed within about 0.5 dB of their simulations.

**What this means:**

* **URC-60 reaches the −30 dB goal in under a minute.** No mode in WSJT-X
  does that in the same time.
* **URC-15 beats FT8 and FST4-15 by about 4 dB** in the same 15 s slot.
* **Against physics:** URC-60 is within about 1 dB of the realistic coherent
  limit for 80 bits in 60 s (≈ −31.7 dB). Large further gains are not
  available. LDPC coding (≈ +1 dB) and multi-receiver combining (+3 dB per
  doubling) are what remain.

## 3. What we learned along the way

1. **A short burst cannot reach −30 dB.** For about 80 bits, −30 dB needs
   roughly a minute on air, or combining repeats or receivers. This is
   physics, not software.
2. **Most of the gain over WSJT-X comes from coherent detection.** URC
   locks the carrier phase from pilots, as long-haul receivers lock onto a
   residual carrier, and that is worth 3–5 dB over noncoherent FSK.
3. **Peak power matters.** The first URC version used filtered BPSK. Its
   3.2 dB peak-to-average ratio would have erased most of the gain on a real
   transmitter. Switching to MSK made it constant-envelope (0.0 dB) with no
   loss of sensitivity.
4. **Frequency accuracy is the price.** URC-60 needs both stations within
   ±0.6 Hz (4 parts per billion at 144 MHz): a GPSDO at each end. Phase
   drift up to 0.1 rad per symbol cost only 0.7 dB.
5. **Stacking repeats gave 3.4 dB, not 6 dB, for 4×** in the noncoherent
   mode, because noncoherent combining is inefficient at very low SNR.
6. **Several ideas don't add decode sensitivity.** Stochastic resonance,
   neural classifiers, RF fingerprinting and fast reconfiguration are useful
   for band monitoring, but not for decoding a known signal in Gaussian
   noise.
7. **Big antennas and quiet receivers still matter.** On 2 m, sky noise
   dominates, so the antenna and a quiet site count more than the preamp.
   On 70 cm, a low-noise masthead preamp is worth having.

## 4. Limits and honest caveats

* **Nothing has been on air yet.** All results are from simulation and audio
  loopback with white Gaussian noise. Real fading, interference and
  oscillator behaviour still need field trials.
* **Fast fading** (aircraft scatter, flutter) will hurt URC more than FST4.
* **Licensing:** the APRS frequencies outside Region 2 are disabled by
  default. Unattended operation and new digital modes need checking with the
  Barbados Telecommunications Unit, and new codes may need public
  documentation (this repository provides it).
* **The URC SNR display** reads 1–2 dB low at strong signals. This is
  cosmetic only.

## 5. Next steps

1. **On-air trial** of URC-60 between two GPSDO-locked stations on 2 m,
   logging decode SNR against a simultaneous FST4W-120 transmission.
2. **LDPC or polar-with-CRC** code for URC: about +1 dB.
3. **Networked multi-receiver combining** (arraying): +3 dB per doubling of
   receivers.
4. **A GNU Radio / SDR front end** feeding the decoder.
5. **A residual-carrier URC variant,** to compare against
   pilots.

Repository: https://github.com/BajanBob/Uranus
