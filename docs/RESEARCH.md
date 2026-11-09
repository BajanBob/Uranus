# Applying the low-SNR research to Uranus

This note takes the ideas from the research review and asks one question of
each: **does it help a 2 m / 70 cm beacon decode at −30 dB?** Some of the
ideas do; others solve different problems.

## 1. The physics sets the budget

For a message of *k* information bits, sent in *D* seconds, decoded at
energy-per-bit *Eb/N0*:

    SNR(2500 Hz) = Eb/N0 + 10·log10( k / (2500 · D) )

The ultimate Shannon limit is Eb/N0 = −1.6 dB. A realistic best for
messages of about 80 bits is about +1 dB with coherent detection, and about
+3 dB with noncoherent FSK (FST4, WSPR, UR).

| Message | Coherent, best realistic | Noncoherent FSK |
|---|---|---|
| 80 bits in 15 s | −25.7 dB | −23.7 dB |
| 80 bits in 60 s | −31.7 dB | −29.7 dB |
| 50 bits in 110 s | −36.4 dB | −34.4 dB |
| 30 bits in 15 s | −30.0 dB | −28.0 dB |

**What this means:** a "short fast burst" at −30 dB is not possible for a
normal-sized message. You can reach −30 dB by:

* transmitting for about 60 s or more,
* sending very few bits, or
* combining several transmissions or receivers.

WSJT-X already sits within about 2–3 dB of these limits. "Better than
WSJT-X" therefore means winning a few dB through better detection, not tens
of dB.

## 2. Each idea from the brief

| Idea | Helps decode at −30 dB? | Status in Uranus |
|---|---|---|
| Long integration / narrow bandwidth | **Yes — the main lever** | UR-60/120/300 submodes |
| Strong channel coding, soft decisions | **Yes** | K=9 r=1/3 conv + soft Viterbi; LDPC/polar on roadmap |
| A-priori decoding (known callsign) | Yes, a little (+0.7 dB measured) | `--expect CALL GRID` |
| Stacking repeats / multichannel correlation | **Yes** (+3.4 dB for 4×, measured) | LLR summation; multi-receiver next |
| Coherent detection with GPSDO | **Yes: +2.7 to +4.0 dB over FST4, measured** | **Built: Pumpkin mode** |
| Accurate time sync (NTP/GPS) | Required | Scheduler checks NTP |
| Cognitive radio / spectrum awareness | Yes, for **not causing interference** | Listen-before-talk on APRS via S-meter |
| CNN / one-class classifiers to find unknown signals | Not for decoding your own known signal; useful for **monitoring** the band | Not built — good later research add-on with an RTL-SDR |
| RF fingerprinting | No; it identifies *which transmitter* sent something | Not built |
| AI radios cooperating to share spectrum | Mainly for networks of many radios | Not applicable to one beacon |
| 50 ns processor reconfiguration | No; these modes change every 15–300 s | Not needed |
| Stochastic resonance | No: for a known signal in Gaussian noise, the matched filter + soft decoder is already optimal; SR only helps crude threshold detectors | Not built |
| Bigger amplifier | Raises signal and noise together, so no SNR gain at the receiver. More **transmit** power does help | — |
| Receiver sensitivity (dBm) vs SNR (dB) | Different measures, as the review says | SNR figures here are all in 2500 Hz |

## 3. Practical way to get −30 dB decodes today

1. **Use FST4W-120 or FST4W-300 in WSJT-X.** They are proven at −32.8 and
   −36.8 dB.
2. **For your own mode, use UR-120,** or UR-60 sent 4 times with stacking.
3. **Keep frequencies stable.** Use a GPSDO- or TCXO-locked rig at both ends;
   at 432 MHz, 1 ppm of drift is 432 Hz. Keep the clock NTP-synced to under
   0.5 s.
4. **Fix the antenna side.** Use a low-noise preamp at the antenna for 70 cm,
   a quiet location and a horizontal yagi. These make the decode easier
   rather than making the decoder better.
