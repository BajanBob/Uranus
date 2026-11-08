"""Monte-Carlo sensitivity measurement for the UR mode.

Two levels:
  * ideal_sync_curve  - symbol-level AWGN, perfect time/frequency sync.
                        Gives the code+modulation threshold quickly.
  * audio_curve       - full audio path: modulator, AWGN, blind time/frequency
                        search and decode. Includes real synchronisation loss.

Threshold = SNR (2500 Hz reference, same as WSJT-X) where 50 % of frames decode.
"""

import numpy as np

from . import urmode as u

CALLS = ["8P6AB", "K1ABC", "G4XYZ", "VE3QQ", "JA1ZZ", "8P9Q", "W9AA", "DL1ABC"]
GRIDS = ["GK03", "FN42", "IO91", "FN03", "PM95", "GK13", "EN52", "JO62"]


def _random_msg(rng):
    i = rng.integers(len(CALLS))
    return CALLS[i], GRIDS[i], int(rng.integers(8)), int(rng.integers(16384))


def ideal_sync_curve(esn0_list, trials=200, repeats=1, ap=False, seed=1):
    rng = np.random.default_rng(seed)
    out = []
    for es in esn0_list:
        ok = 0
        for _ in range(trials):
            call, grid, mt, val = _random_msg(rng)
            tones = u.message_to_tones(call, grid, mt, val)
            llr = np.zeros(u.NCODED)
            for _ in range(repeats):
                Y, a = u.awgn_tone_outputs(tones, es, rng)
                llr += u.tone_llrs(Y, a, 1.0)
            known = u.known_bits(call, grid) if ap else None
            m = u.decode_llr(llr, known)
            ok += bool(m and m["call"] == call and m["value"] == val)
        out.append(ok / trials)
    return np.array(out)


def audio_curve(snr_list, submode="UR-15", trials=40, seed=2):
    rng = np.random.default_rng(seed)
    out = []
    for snr in snr_list:
        ok = 0
        for _ in range(trials):
            call, grid, mt, val = _random_msg(rng)
            f0 = rng.uniform(800, 2200)
            y = u.modulate(u.message_to_tones(call, grid, mt, val), submode, f0=f0)
            pad = np.zeros(int(rng.uniform(0.5, 2.5) * u.FS))
            x = np.concatenate([pad, y, np.zeros(u.FS)]).astype(float)
            sigma = np.sqrt(np.mean(y ** 2) / (10 ** (snr / 10) * 2500 * 2 / u.FS))
            x += sigma * rng.standard_normal(len(x))
            res = u.decode_audio(x, submode)
            ok += any(r["call"] == call and r["value"] == val for r in res)
        out.append(ok / trials)
    return np.array(out)


def threshold(xs, ps, level=0.5):
    """Linear interpolation of where the decode probability crosses `level`."""
    xs, ps = np.asarray(xs, float), np.asarray(ps, float)
    for i in range(len(xs) - 1):
        if (ps[i] - level) * (ps[i + 1] - level) <= 0 and ps[i] != ps[i + 1]:
            return xs[i] + (level - ps[i]) * (xs[i + 1] - xs[i]) / (ps[i + 1] - ps[i])
    return float("nan")
