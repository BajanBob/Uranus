# URC mode — coherent Uranus mode with carrier recovery (v0.2)

URC brings the classic recipe for very weak, long-distance links to a
2 m / 70 cm beacon: a known reference for carrier lock, coherent
demodulation, a narrow effective bandwidth and strong convolutional coding. It is the first Uranus
mode that **beats WSJT-X FST4 at the same slot length and the same
transmitter peak power**.

## Signal

| Item | Value |
|---|---|
| Payload | 64 bits (same as UR): callsign, grid, type, value |
| Integrity | CRC-16/CCITT |
| FEC | Convolutional K = 9, r = 1/3 (557/663/711), soft Viterbi → 264 bits |
| Pilots | 1 known symbol after every 4 data symbols (66 pilots, PRBS7 ±1). This is the "residual carrier" |
| Modulation | **MSK**: baseband Σ b_k·j^k·halfsine(t−kT). Constant envelope, so the peak-to-average ratio is **0.0 dB measured** |
| Frame | 330 symbols, starting 1 s after a UTC multiple of the period |

| Submode | Symbol T | On air | Main lobe | Frequency tolerance |
|---|---|---|---|---|
| URC-15 | 0.04 s | 13.2 s | 37.5 Hz | ±2.5 Hz |
| URC-30 | 0.08 s | 26.4 s | 18.8 Hz | ±1.25 Hz |
| URC-60 | 0.16 s | 52.8 s | 9.4 Hz | ±0.6 Hz |
| URC-120 | 0.32 s | 105.6 s | 4.7 Hz | ±0.3 Hz |
| URC-300 | 0.8 s | 264 s | 1.9 Hz | ±0.12 Hz |

The frequency tolerance comes from the pilot spacing (±1 / (10·T)). At
144 MHz, ±0.6 Hz is 4 parts per billion, so **both stations need a GPSDO**.
Knowing the frequency this precisely is what lets the receiver search a
tiny window.

## Receiver (the carrier-recovery chain)

1. **Mix down and matched filter.** The audio is mixed down at the nominal
   frequency and passed through a half-sine matched filter.
2. **Joint timing and frequency search.** For each timing candidate (T/8
   steps), an FFT of the pilot-wiped samples finds the carrier offset.
3. **Carrier tracking.** A complex-phasor Kalman filter plus an RTS smoother
   runs over the pilots. It predicts the carrier's motion, and the backward
   pass also uses later pilots. This does the job of a narrow phase-locked loop,
   and because it works offline it can do better than a real-time loop.
4. **Decoding.** Coherent LLRs go into a soft Viterbi decoder (with optional
   a-priori bits), then a CRC check.

## Measured sensitivity (50 % decode, SNR in 2500 Hz)

| Submode | Simulated, GPSDO-class oscillators | **Full audio, blind sync** | FST4 / FST4W (WSJT-X) | Gain over FST4 |
|---|---|---|---|---|
| URC-15 | −25.1 | **−24.7** | −20.7 | **+4.0 dB** |
| URC-30 | −28.1 | — | −24.2 | ≈ +3.9 dB |
| URC-60 | −31.1 | **−30.8** | −28.1 | **+2.7 dB** |
| URC-120 | −34.1 | — | −31.3 / −32.8 | ≈ +1.3 to +2.8 dB |
| URC-300 | −38.1 | — | −35.3 / −36.8 | ≈ +1.3 to +2.8 dB |

The "—" cells were not measured through the audio path. Expect them to land
within about 0.5 dB of the simulation, as the measured submodes did.

The simulation includes random frequency errors up to ±0.2 Hz and random
phase drift of 0.01 rad per symbol. Robustness of URC-60 to phase drift:

| Phase random walk per symbol | Threshold |
|---|---|
| 0.01 rad | −31.0 dB |
| 0.03 rad | −31.0 dB |
| 0.05 rad | −30.8 dB |
| 0.10 rad | −30.4 dB |

Frequency offsets beyond the tolerance column cause decoding to fail
completely. That is why a GPSDO is required.

## Why it wins, and its limits

* **Coherent detection beats noncoherent 4-FSK** by about 3–5 dB at these
  code rates. That is the whole gain, and the reason long-haul links keep a
  carrier reference.
* **The 20 % pilot overhead costs about 1 dB.** It is already included in
  the numbers above.
* **Constant-envelope MSK** keeps the gain at equal peak power. An earlier
  filtered-BPSK version had 3.2 dB peak-to-average and would have lost most
  of the advantage.
* **The limits:** it needs GPSDO-class frequency accuracy at both ends, and
  fast fading (aircraft scatter, multipath flutter) will hurt it more than
  FST4.
* **The reported SNR reads about 1–2 dB low** at high SNR. That is a display
  issue only.

## Next steps

* **LDPC or polar-with-CRC code** instead of K = 9: about +1 dB.
* **Multi-receiver combining** of URC LLRs over the network (arraying): +3 dB
  per doubling.
* **An optional residual-carrier variant**, with no
  pilots: the trade-off needs measuring.
* **A GNU Radio front end** for SDR receivers.
