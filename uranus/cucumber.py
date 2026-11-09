"""Cucumber - weak-signal beacon mode for ordinary FM radios.

Cucumber sends the Pumpkin waveform (constant-envelope MSK, pilots, K=9 r=1/3
code, CRC) as an AUDIO signal centred on 1500 Hz through an FM transmitter,
and decodes it from an FM receiver's audio.

Why this works so well on FM:
  * An FM receiver returns the transmitted audio frequency exactly, whatever
    the radio's own frequency error. The audio comes from a sound card, so
    the pilots can be tracked coherently with no GPS oscillator at either end
    (a 50 ppm sound-card clock is only 0.08 Hz at 1500 Hz).
  * The decoder integrates over the whole frame, so it keeps working well
    below the FM "threshold" (about +10 dB in the channel) where voice and
    APRS stop: in simulation it decodes down to about -11 dB (CUCUMBER-15)
    and -13 dB (CUCUMBER-60) carrier-to-noise in a 12.5 kHz channel.

What it cannot do: FM gives away weak-signal headroom, so Cucumber is about
25 dB less sensitive than Pumpkin on SSB. Fading and Doppler of the radio
path are not visible in FM audio, so no channel metrics are reported.

Operating notes: open the squelch fully, feed audio through the data port
(flat response, no mic compressor), and set about 2.5 kHz peak deviation.
"""

import numpy as np
from scipy.signal import firwin, lfilter, resample_poly

from . import pumpkin

FS = pumpkin.FS
SUBMODES = {"CUCUMBER-" + k.split("-")[1]: v for k, v in pumpkin.SUBMODES.items()}
PERIODS = {k: int(k.split("-")[1]) for k in SUBMODES}
NSYM = pumpkin.NSYM
AUDIO_F0 = 1500.0


def _pk(submode):
    return "PUMPKIN-" + submode.split("-")[1]


def message_to_symbols(call, grid, mtype=0, value=0, bits=None):
    return pumpkin.message_to_symbols(call, grid, mtype, value, bits=bits)


def modulate(symbols, submode="CUCUMBER-60", amp=0.5):
    """Audio for the FM transmitter's data input."""
    return pumpkin.modulate(symbols, _pk(submode), f0=AUDIO_F0, amp=amp)


def decode_audio(x, submode="CUCUMBER-60", fs=FS, df_max=0.5, known=None):
    res = pumpkin.decode_audio(x, _pk(submode), fs=fs, f_nom=AUDIO_F0, df_max=df_max, known=known)
    for r in res:
        r.pop("fade_db", None)               # FM audio hides RF fading and Doppler
        r.pop("spread_hz", None)
        r["audio_snr"] = r.pop("snr")         # post-detection audio SNR, not RF
    return res


# --------------------------------------------------------------------------- FM channel model
def fm_channel(audio, cnr_db, rng, fs_audio=FS, up=4, dev_hz=2500.0, if_bw=12500.0):
    """Narrow-band FM link: modulator, AWGN at `cnr_db` carrier-to-noise in
    `if_bw`, IF filter, discriminator, audio filter. Returns receiver audio."""
    fs = fs_audio * up
    a = np.asarray(audio, float)
    a = a / (np.max(np.abs(a)) or 1.0)
    m = resample_poly(a, up, 1)
    z = np.exp(1j * 2 * np.pi * dev_hz * np.cumsum(m) / fs)
    n0 = 10 ** (-cnr_db / 10) * fs / if_bw
    z = z + np.sqrt(n0 / 2) * (rng.standard_normal(len(z)) + 1j * rng.standard_normal(len(z)))
    z = lfilter(firwin(129, if_bw / 2, fs=fs), 1, z)
    d = np.angle(z[1:] * np.conj(z[:-1])) * fs / (2 * np.pi)
    d = lfilter(firwin(129, 3000, fs=fs), 1, d)
    return resample_poly(d, 1, up)
