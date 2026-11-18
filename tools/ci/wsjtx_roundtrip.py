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

# Q65-60A: WSJT-X's own simulator makes a -26 dB slot; Uranus's jt9 wrapper must decode it
import glob, os, shutil, subprocess, tempfile, wave   # noqa: E401,E402
if shutil.which("q65sim"):
    d = tempfile.mkdtemp()
    subprocess.run(["q65sim", "8P5AB K1ABC FN42", "A", "1500", "0.0", "0.0", "0.0", "1", "60", "1", "1", "-26"],
                   cwd=d, capture_output=True, check=True)
    w = wave.open(sorted(glob.glob(os.path.join(d, "*.wav")))[0])
    q = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
    wsjt.set_station("8P5AB", "GK03")
    res = wsjt.q65_decode(q, 144_170_000)
    print("Q65 -26 dB:", res)
    assert any(r["call"] == "K1ABC" and r["grid"] == "FN42" for r in res), res

# Q65 transmit: Uranus's own Q65 audio (q65code tones) at -24 dB must decode in jt9
qa = wsjt.q65_audio("CQ 8P5AB GK03", f0=1200.0)
slot = np.zeros(60 * fs)
slot[fs:fs + len(qa)] += qa                                   # 1 s into the minute, as the beacon sends it
sig = slot / np.sqrt(np.mean(qa ** 2)) * np.sqrt(2500 / (fs / 2)) * 10 ** (-24 / 20)
res = wsjt.q65_decode(rng.normal(0, 1, len(slot)) + sig, 144_170_000)
print("Q65 TX -24 dB:", res)
assert any(r["call"] == "8P5AB" and r["grid"] == "GK03" and abs(r["freq_hz"] - 144_171_200) < 5 for r in res), res


def sim_wav(args, d=None):
    d = d or tempfile.mkdtemp()
    subprocess.run(args, cwd=d, capture_output=True, check=True)
    w = wave.open(sorted(glob.glob(os.path.join(d, "*.wav")))[0])
    return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768


# JT65, FST4 and FST4W (receive-only listen modes) from WSJT-X's own simulators
if shutil.which("jt65sim"):
    res = wsjt.jt65_decode(sim_wav(["jt65sim", "-n", "1", "-m", "A", "-s", "\\-20", "-f", "1"]), 14_076_000)
    print("JT65 -20 dB:", res)
    assert any(r["call"] == "W9XYZ" for r in res), res
if shutil.which("fst4sim"):
    res = wsjt.fst4_decode(sim_wav(["fst4sim", "K1JT K9AN EN50", "60", "1500", "0.0", "0.1", "1.0", "1", "-20", "F"]),
                           474_200)
    print("FST4 -20 dB:", res)
    assert any(r["call"] == "K9AN" and r["grid"] == "EN50" for r in res), res
    res = wsjt.fst4w_decode(sim_wav(["fst4sim", "K1JT FN20 30", "120", "1500", "0.0", "0.1", "1.0", "1", "-27", "T"]),
                            14_095_600)
    print("FST4W -27 dB:", res)
    assert any(r["call"] == "K1JT" and r["grid"] == "FN20" and r["dbm"] == 30 for r in res), res

# AUTO decodes FT8 first: a crowded FT8 slot must come back as FT8 decodes, with no guess left beside them
import tomllib                                         # noqa: E401,E402
from uranus import monitor                                   # noqa: E402
cfg = tomllib.loads(open("config/uranus.toml", encoding="utf-8").read())
cfg["receive"] = {"mode": "auto", "dial_mhz": 14.074}
events = []
lis = monitor.Listener(cfg, spot_path=tempfile.mktemp(), on_event=events.append)
slot = np.zeros(15 * fs)
for k, (msg, f0) in enumerate((("CQ 8P5AB GK03", 600.0), ("CQ K1ABC FN42", 1100.0), ("CQ W9XYZ EN37", 1700.0),
                               ("CQ G4ABC IO91", 2300.0))):
    a = wsjt.ft8_audio(msg, f0=f0)
    slot[int(0.5 * fs):int(0.5 * fs) + len(a)] += a / np.sqrt(np.mean(a ** 2))
x = rng.normal(0, 1, len(slot)) + slot * np.sqrt(2500 / (fs / 2)) * 10 ** (-10 / 20)
lis.block_t0 = 0.0
name, res = lis._auto(x)
calls = sorted(r["call"] for r in res if r["mode_name"] == "FT8")
print("AUTO:", calls, [(i["mode"], round(i["freq_hz"])) for e in events for i in e["items"]])
assert calls == ["8P5AB", "G4ABC", "K1ABC", "W9XYZ"], calls
assert lis.follow is None
print("WSJT-X round trip OK")
