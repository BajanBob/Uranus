"""Linux CI: real WSJT-X encoders -> noise -> Uranus's jt9 / wsprd decoder wrappers."""
import sys

import numpy as np

sys.path.insert(0, ".")
from uranus import wsjt                      # noqa: E402

rng = np.random.default_rng(1)
fs = wsjt.FS

ft8 = wsjt.ft8_audio("CQ 8P5AB GK03", f0=1200.0)
slot = np.zeros(15 * fs)
slot[int(0.5 * fs):int(0.5 * fs) + len(ft8)] += ft8            # FT8 starts 0.5 s into the slot
noise = rng.normal(0, 1, len(slot))
sig = slot / np.sqrt(np.mean(ft8 ** 2)) * np.sqrt(2500 / (fs / 2)) * 10 ** (-12 / 20)   # about -12 dB in 2500 Hz
res = wsjt.ft8_decode(noise + sig, 144_174_000)
print("FT8:", res)
assert any(r["call"] == "8P5AB" and r["grid"] == "GK03" for r in res), res
assert all(abs(r["freq_hz"] - 144_175_200) < 10 for r in res if r["call"] == "8P5AB")

w = wsjt.wspr_audio("8P5AB", "GK03", 23, f0=1500.0)
slot = np.zeros(114 * fs)
slot[int(1 * fs):int(1 * fs) + len(w)] += w[: len(slot) - fs]
sig = slot / np.sqrt(np.mean(w ** 2)) * np.sqrt(2500 / (fs / 2)) * 10 ** (-20 / 20)    # about -20 dB
res = wsjt.wspr_decode(rng.normal(0, 1, len(slot)) + sig, 144_489_000)
print("WSPR:", res)
assert any(r["call"] == "8P5AB" and r["grid"] == "GK03" and r["dbm"] == 23 for r in res), res
print("WSJT-X round trip OK")
