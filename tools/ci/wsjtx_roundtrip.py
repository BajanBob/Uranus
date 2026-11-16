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

# Charger noise (whistles + buzz clicks): FT8 at -16 dB through Uranus's noise filter
from uranus.noisefilter import NoiseFilter   # noqa: E402
t = np.arange(len(slot)) / fs


def charger(n):
    x = rng.normal(0, 1, n)
    for f, a in ((620, 4), (1180, 3), (2240, 4)):
        x += a * np.sin(2 * np.pi * f * t)
    for i in range(0, n - 20, 100):
        x[i:i + 6] += rng.choice([-1, 1]) * 25 * np.exp(-np.arange(6) / 2)
    return x


nf = NoiseFilter(fs)
for _ in range(4):
    nf.clean(charger(len(slot)))
sig16 = sig * 10 ** (-4 / 20)
raw = charger(len(slot)) + sig16
res_raw = wsjt.ft8_decode(raw, 144_174_000)
res_f = wsjt.ft8_decode(nf.clean(raw), 144_174_000)
print("FT8 with charger noise: raw", [r["message"] for r in res_raw], "| filtered", [r["message"] for r in res_f],
      "|", nf.describe())
assert any(r["call"] == "8P5AB" for r in res_f), res_f

ft4 = wsjt.ft4_audio("CQ 8P5AB GK03", f0=1800.0)
slot = np.zeros(int(7.5 * fs))
slot[int(0.5 * fs):int(0.5 * fs) + len(ft4)] += ft4
sig = slot / np.sqrt(np.mean(ft4 ** 2)) * np.sqrt(2500 / (fs / 2)) * 10 ** (-8 / 20)     # about -8 dB
res = wsjt.ft4_decode(rng.normal(0, 1, len(slot)) + sig, 14_080_000)
print("FT4:", res)
assert any(r["call"] == "8P5AB" and r["grid"] == "GK03" for r in res), res
assert all(abs(r["freq_hz"] - 14_081_800) < 15 for r in res if r["call"] == "8P5AB")

w = wsjt.wspr_audio("8P5AB", "GK03", 23, f0=1500.0)
slot = np.zeros(114 * fs)
slot[int(1 * fs):int(1 * fs) + len(w)] += w[: len(slot) - fs]
sig = slot / np.sqrt(np.mean(w ** 2)) * np.sqrt(2500 / (fs / 2)) * 10 ** (-20 / 20)    # about -20 dB
res = wsjt.wspr_decode(rng.normal(0, 1, len(slot)) + sig, 144_489_000)
print("WSPR:", res)
assert any(r["call"] == "8P5AB" and r["grid"] == "GK03" and r["dbm"] == 23 for r in res), res
print("WSJT-X round trip OK")
