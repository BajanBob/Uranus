# Signal identification (AUTO)

Choose **AUTO** in the Receiver panel's Decode list. Every 15 seconds Uranus looks at
everything in the receiver's passband (about 0-3 kHz above the dial), works out what
each signal is from its **signature**, tags it on the waterfall, and sends it to the right
decoder by itself.

## What it measures

| Feature | How | Separates |
|---|---|---|
| Bandwidth | fine averaged spectrum, -10 dB width | WSPR (6 Hz) from FT8 (50 Hz) from voice (2.4 kHz) |
| Keying speed (baud) | the instantaneous frequency jumps once per symbol: a spectral line at the baud rate | FT8 6.25, FT4 20.8, WSPR 1.46, PSK31 31.25 |
| MSK test | squaring an MSK signal gives exactly two lines one baud apart | Pumpkin |
| Tones | bandwidth / baud | FT8 about 8, WSPR and FT4 4, Pumpkin 1.5 |
| Length | activity span, or cumulative energy for weak broken-up signals | FT8 12.6 s, UR-15 13.1 s, WSPR 110.6 s |
| UTC slot | start time against :00/:15/:30/:45 + 0.5 s, even minute + 1 s... | FT8, FT4, WSPR, JT65, Pumpkin, UR |
| Envelope | constant, keyed on/off (5 ms detail), dips at 31.25 Hz, speech rhythm | FSK, CW, PSK31, SSB voice |
| Two tones | pairs that come and go together, by shift | RTTY 170 Hz, HF packet 200 Hz, APRS 1200/2200 Hz |
| Decoding | packets are confirmed by decoding them (CRC-checked) | APRS, HF APRS |

Each match comes with a confidence and the reasons, in plain words. A signal seen again on
the same frequency gains confidence (memory of the last 10 minutes).

## Signatures in the library

FT8, FT4, WSPR, JT65, APRS / packet 1200, HF packet / APRS 300, RTTY, PSK31, CW,
carriers, SSB voice, PUMPKIN-15 to -300 (CUCUMBER when heard through FM) and UR-15 to -300.

## What AUTO does with them

* **FT8 and FT4**: decoded at once with WSJT-X's decoder (install WSJT-X); each 15-second block holds
  two FT4 slots and both are decoded.
* **APRS and HF packet**: decoded at once with Uranus's own packet decoder.
* **WSPR, Pumpkin, UR**: these need a whole slot. When one appears twice in a row, AUTO
  follows it for one full slot with the right decoder, then goes back to watching.
* **CW, RTTY, PSK31, voice, carriers**: identified and shown; Uranus has no decoder for them.

## Tested performance (simulation, white noise)

All 14 signal types above are identified correctly at moderate signal levels; no false
identifications in noise alone; four signals at once are separated. Weakest correctly
identified (SNR in 2500 Hz): FT8 -15 dB, Pumpkin-60 -16 dB, WSPR -22 dB. Real bands add
fading, interference and drifting signals, so expect lower confidence on the air.
