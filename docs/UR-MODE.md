# UR mode — Uranus experimental weak-signal beacon mode (v0.1)

A WSPR/FST4-style beacon mode, written from scratch so every part of the
receiver can be experimented with. **It does not beat WSJT-X yet**. The
numbers below are measured, and they show where it stands.

## Signal

| Item | Value |
|---|---|
| Payload | 64 bits: callsign 32 (base-37, ≤ 6 chars), grid 15, message type 3, value 14 (0–16383) |
| Integrity | CRC-16/CCITT → 80 bits |
| FEC | Convolutional K = 9, rate 1/3, generators 557/663/711 (octal), zero tail → 264 bits |
| Interleaver | channel bit *i* = coded bit (97·*i* mod 264) |
| Modulation | 4-GFSK (BT = 1), Gray mapped, continuous phase, tone spacing = 1/T |
| Frame | `S8 D44 S8 D44 S8 D44 S8` = 164 symbols (32 sync, pattern 0,1,3,2,1,0,2,3) |
| Timing | starts 1 s after a UTC multiple of the submode period |

| Submode | Symbol T | On air | Width |
|---|---|---|---|
| UR-15 | 0.08 s | 13.1 s | 50 Hz |
| UR-30 | 0.16 s | 26.2 s | 25 Hz |
| UR-60 | 0.32 s | 52.5 s | 12.5 Hz |
| UR-120 | 0.64 s | 105 s | 6.3 Hz |
| UR-300 | 1.6 s | 262 s | 2.5 Hz |

## Receiver

1. A short-time FFT (4× oversampled in time and frequency) is searched for
   the 32 sync symbols over 300–2700 Hz and 0–4 s offsets.
2. Noise N0 is estimated from the spectrogram median and the signal amplitude
   from the sync symbols.
3. The exact noncoherent bit LLRs (log I0) go into a soft Viterbi decoder.
4. **A-priori (AP) decoding.** If you pass `--expect CALL GRID`, those 47
   bits are forced in the trellis.
5. **Stacking.** LLRs from repeated frames, or from several receivers hearing
   the same frame, are added together before decoding.
6. CRC-16 plus field checks reject false decodes. A 20 s noise-only test gave
   no decodes.

## Measured sensitivity (50 % decode, SNR in 2500 Hz, as WSJT-X quotes it)

These come from `python -m uranus ur-sim` with 150 trials per point and
perfect synchronisation. The full audio path with blind sync measured about
0.6 dB worse: UR-15 −19.4 dB and UR-60 −25.4 dB.

| Submode | UR plain | UR + AP | UR, 4 repeats stacked | FST4 (WSJT-X) | FST4W |
|---|---|---|---|---|---|
| UR-15 | −20.0 | −20.7 | −23.4 | −20.7 | — |
| UR-30 | −23.0 | −23.7 | −26.5 | −24.2 | — |
| UR-60 | −26.0 | −26.7 | −29.5 | −28.1 | — |
| UR-120 | −29.0 | −29.8 | −32.5 | −31.3 | −32.8 |
| UR-300 | −33.0 | −33.7 | −36.5 | −35.3 | −36.8 |

The FST4/FST4W figures are from the WSJT-X FST4 Quick-Start Guide.

What these numbers show:

* Single-frame UR is **0.7–2.3 dB behind FST4**. FST4 uses a stronger LDPC
  code and multi-symbol block detection.
* Stacking 4 repeats gained **3.4 dB, not the ideal 6 dB**. Noncoherent
  detection loses efficiency when each frame is very weak.
* AP decoding gained only about 0.7 dB with this convolutional code.

## Can it reach −30 dB?

Yes, but only by spending time:

* **UR-120** reaches about −29 dB from one frame.
* **UR-60 heard 4 times** (about 4 minutes) reaches about −29.5 dB.
* **UR-300** reaches −33 dB.

A short, fast burst cannot reach −30 dB; see `RESEARCH.md` for the physics.

## Roadmap, in order of expected gain

1. **Coherent detection.** Both ends need a GPSDO; 2 m and 70 cm line-of-sight
   and tropo paths are often phase-stable. Expected gain is about +2 to 3 dB,
   needing pilot symbols and a phase-tracking loop.
2. **Multi-symbol block detection,** as in FST4: about +1.5 dB.
3. **Replace the convolutional code** with an LDPC code or a CRC-aided polar
   list decoder: about +1 dB.
4. **Stack across receivers.** Several Pis with RTL-SDRs share LLRs over the
   network, using the same code path as repeats.

Before transmitting a new mode on air, check your licence. Many
administrations require the technical characteristics of a new digital code
to be publicly documented. This file is a start, but confirm what the
Barbados Telecommunications Unit requires.
