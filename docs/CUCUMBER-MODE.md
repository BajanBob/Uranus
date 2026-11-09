# Cucumber — weak-signal beacon mode for ordinary FM radios

Cucumber carries the Pumpkin signal as **audio** through any FM transmitter
and decodes it from any FM receiver's audio. It is designed for the many
FM-only radios, especially on 1.25 m (220 MHz), where almost no radio has
SSB.

## How it works

* The Pumpkin waveform (constant-envelope MSK at 1500 Hz audio, pilot
  symbols, K = 9 rate ⅓ convolutional code, CRC-16, 64-bit message) is fed
  to the FM transmitter's data input at about 2.5 kHz peak deviation.
* **No GPS oscillator is needed.** An FM receiver returns the audio
  frequency exactly as the sending sound card made it, whatever the radio's
  own frequency error, so the decoder can still track the pilots coherently.
* **It works below FM's threshold.** Ordinary FM collapses into noise below
  about +10 dB in the channel. Cucumber integrates over the whole frame, so it
  keeps decoding far below that point.

## Measured sensitivity (simulation)

The test link: narrow-band FM, 12.5 kHz receiver bandwidth, 2.5 kHz
deviation, white noise, and a ±50 ppm sound-card clock error.

| Mode | On air | Decodes down to (carrier-to-noise in 12.5 kHz) | Same, as SNR in 2500 Hz |
|---|---|---|---|
| FM voice / APRS (for comparison) | — | about +10 dB | about +17 dB |
| **CUCUMBER-15** | 13.2 s | **about −11 dB** | about −4 dB |
| **CUCUMBER-60** | 52.8 s | **about −13 dB** | about −6 dB |

That is **more than 20 dB below where FM voice or APRS works on the same
radio**. It is still about 25 dB less sensitive than Pumpkin on SSB: FM
gives away weak-signal headroom and nothing gets it back. Field results
on real radios are still needed.

## Operating notes

* **Squelch:** open fully. A closed squelch hides weak signals.
* **Audio path:** use the radio's **data port** (flat audio, no mic
  compressor), or an interface such as a Digirig.
* **Level:** set the audio so peaks reach about 2.5 kHz deviation
  (narrow-band FM).
* **Channel:** agree a simplex channel locally. Uranus defaults to
  223.420 MHz on 1.25 m, clear of the 223.500 MHz calling frequency; the
  2 m and 70 cm Cucumber slots are off until you choose a channel.
* **What gets reported:** decodes go to PSK Reporter as mode `CUCUMBER` at the
  channel frequency, and appear on the station map.
* **Propagation measurements:** FM audio hides the radio path's fading and
  Doppler, so Cucumber decodes carry no channel measurements. The
  propagation analyst uses distance, band, time and path instead.

## Try it

```bash
python -m uranus cucumber-loopback --submode CUCUMBER-15 --cnr -8   # simulated FM link
python -m uranus cucumber-encode "8P5AB GK03" cucumber.wav           # audio for your FM rig
python -m uranus cucumber-decode recording.wav                       # decode a recording
```
