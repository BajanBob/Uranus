"""Signal identification: recognise known signals in the receiver passband by their signatures.

Every mode leaves a fingerprint in the audio:
  * bandwidth, and the number and spacing of its tones
  * keying speed (how often the tone changes)
  * how long one transmission lasts
  * when it starts relative to the UTC clock (FT8 at :00/:15/:30/:45 + 0.5 s, WSPR on even minutes + 1 s)
  * the envelope: constant (FSK, MSK), keyed on/off (CW), dipping at the symbol rate (PSK31) or syllabic (voice)

`identify()` measures these for every signal it finds and scores them against a library of known
signatures, returning the best match, a confidence, and the reasons in plain English. `Memory` adds
context over time: a signal seen again on the same frequency gains confidence.

The audio is the receiver's passband (USB dial + 0-3 kHz, or FM audio).
"""

from dataclasses import dataclass, field
import math
import time

import numpy as np

FS = 12000


@dataclass
class Signature:
    mode: str
    family: str                   # what to do with it: "ft8", "wspr", "aprs", "pumpkin", "ur", ... or "" (info)
    n_tones: int = None
    spacing: float = None         # Hz between adjacent tones
    bw: float = None              # occupied bandwidth, Hz
    baud: float = None            # symbols per second
    dur: float = None             # seconds per transmission
    period: float = None          # UTC slot length, seconds
    offset: float = None          # start offset within the slot, seconds
    envelope: str = "constant"    # constant, keyed, steady, psk, syllabic, burst
    note: str = ""

    @property
    def ratio(self):
        """Bandwidth / baud: about the number of tones for FSK (FT8 8, WSPR 4), 1.5 for MSK."""
        return self.bw / self.baud if self.bw and self.baud else None


def _library():
    lib = [
        Signature("FT8", "ft8", 8, 6.25, 50, 6.25, 12.64, 15, 0.5, note="8-GFSK, WSJT-X"),
        Signature("FT4", "ft4", 4, 20.83, 83, 20.83, 4.48, 7.5, 0.5, note="4-GFSK, WSJT-X contest mode"),
        Signature("WSPR", "wspr", 4, 1.465, 6, 1.465, 110.6, 120, 1.0, note="4-FSK beacon, 2-minute slots"),
        Signature("Q65", "q65", 65, 1.667, 108, 1.667, 51.0, 60, 1.0, note="65-FSK, WSJT-X weak-signal VHF (Q65-60A)"),
        Signature("JT65", "", 65, 2.69, 178, 2.69, 46.8, 60, 1.0, note="65-FSK, WSJT"),
        Signature("CW", "", 1, None, 12, None, None, None, None, "keyed", "Morse: one tone keyed on and off"),
        Signature("Carrier", "", 1, None, 3, None, None, None, None, "steady", "unmodulated tone or beacon carrier"),
        Signature("PSK31", "", 1, None, 38, 31.25, None, None, None, "psk", "BPSK, envelope dips 31.25 times a second"),
        Signature("RTTY", "", 2, 170, 230, 45.45, None, None, None, "constant", "2-FSK, 170 Hz shift, 45 baud"),
        Signature("HF packet / APRS 300", "aprs_hf", 2, 200, 500, 300, 1.5, None, None, "burst",
                  "AFSK 300 baud, 200 Hz shift (HF APRS)"),
        Signature("APRS / packet 1200", "aprs", 2, 1000, 2000, 1200, 1.0, None, None, "burst",
                  "Bell 202 AFSK 1200/2200 Hz (VHF APRS)"),
        Signature("SSB voice", "", None, None, 2200, None, None, None, None, "syllabic", "speech, 300-2700 Hz"),
    ]
    from . import pumpkin, urmode
    for sub, T in pumpkin.SUBMODES.items():
        lib.append(Signature(sub, "pumpkin", 2, 0.5 / T, 1.0 / T, 1 / T, pumpkin.NSYM * T, pumpkin.PERIODS[sub],
                             1.0, note="MSK, Uranus coherent mode (CUCUMBER when heard through FM)"))
    for sub, T in urmode.SUBMODES.items():
        lib.append(Signature(sub, "ur", 4, 1 / T, 3.6 / T, 1 / T, urmode.NSYM * T, urmode.PERIODS[sub], 1.0,
                             note="4-GFSK, Uranus mode"))
    return lib


LIBRARY = _library()


@dataclass
class Detection:
    mode: str
    family: str
    freq_hz: float                # centre, audio Hz above the dial
    bw_hz: float
    confidence: float             # 0-1
    start_s: float                # within the block
    dur_s: float
    snr_db: float                 # rough, in 2500 Hz
    reasons: list = field(default_factory=list)
    features: dict = field(default_factory=dict)
    seen: int = 1

    def summary(self):
        return f"{self.mode} at {self.freq_hz:.0f} Hz, {self.confidence:.0%}"


# --------------------------------------------------------------------------- spectrograms
def _spectrogram(x, nfft, hop):
    win = np.hanning(nfft)
    n = 1 + max(0, (len(x) - nfft) // hop)
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * win
    return np.abs(np.fft.rfft(frames, axis=1)) ** 2


def _noise_floor(S, width_bins):
    """Per-bin noise floor: median over time, then a running median across frequency (removes signals)."""
    m = np.median(S, axis=0)
    from scipy.ndimage import median_filter
    # noise power per cell is exponentially distributed: its median is ln 2 times its mean
    return np.maximum(median_filter(m, size=width_bins, mode="nearest") / math.log(2), 1e-20)


def _runs(mask):
    """(start, length) of True runs."""
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    return list(zip(starts, ends - starts))


def _close_gaps(mask, max_gap):
    out = mask.copy()
    runs = _runs(~mask)
    for s, n in runs:
        if 0 < s and s + n < len(mask) and n <= max_gap:
            out[s:s + n] = True
    return out


def _peaks(hist, rel=0.15, min_sep=2):
    p = [i for i in range(1, len(hist) - 1)
         if hist[i] >= hist[i - 1] and hist[i] > hist[i + 1] and hist[i] >= rel * hist.max()]
    keep = []
    for i in sorted(p, key=lambda i: -hist[i]):
        if all(abs(i - k) >= min_sep for k in keep):
            keep.append(i)
    return sorted(keep)


# --------------------------------------------------------------------------- feature extraction
def _welch(x, nfft):
    hop = nfft // 2
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    return _spectrogram(x, nfft, hop).mean(axis=0)


def _baud(seg, fc, bw):
    """Keying speed from the instantaneous frequency: it jumps once per symbol, which puts a spectral line
    at the baud rate in |d(frequency)/dt|. Returns (baud or None, line strength).
    A signal cannot key much faster than its bandwidth, nor (for the modes here) slower than bw/12."""
    n = len(seg)
    if n < FS // 2 or bw < 2.5:
        return None, 0.0
    lo_b, hi_b = max(0.4, bw / 12), 1.6 * bw + 2
    if bw < 25 and n > 4 * 16384:              # slow narrow modes: track the peak in a fine spectrogram
        S = _spectrogram(seg, 16384, 1024)
        df = FS / 16384
        k0, k1 = int((fc - bw) / df), int((fc + bw) / df) + 1
        tr = np.argmax(S[:, k0:k1], axis=1).astype(float)
        g = np.abs(np.diff(tr))
        G = np.abs(np.fft.rfft(g - g.mean()))
        gf = np.fft.rfftfreq(len(g), 1024 / FS)
        band = (gf >= lo_b) & (gf <= min(hi_b, 0.45 * FS / 1024))
        if band.sum() >= 8:
            ref = np.median(G[band]) + 1e-12
            k = int(np.argmax(np.where(band, G, 0)))
            if G[k] / ref > 6:
                return float(gf[k]), float(G[k] / ref)
    X = np.fft.fft(seg)
    fr = np.fft.fftfreq(n, 1 / FS)
    half = bw / 2 + max(3.0, 0.3 * bw)
    sel = np.where((fr > fc - half) & (fr < fc + half))[0]
    Z = np.zeros(n, complex)
    k0 = int(round(fc * n / FS))
    Z[(sel - k0) % n] = X[sel]
    z = np.fft.ifft(Z)
    D = max(1, int(FS // max(8 * half, 40)))
    z, fsd = z[::D], FS / D
    msk = _msk_lines(z, fsd, lo_b, hi_b)
    if msk:
        return msk
    finst = np.angle(z[1:] * np.conj(z[:-1])) * fsd / (2 * np.pi)
    amp = np.abs(z[1:])
    w = np.minimum(amp / (np.median(amp) + 1e-12), 2.0)
    g = np.abs(np.diff(finst)) * w[1:]
    if len(g) < 16:
        return None, 0.0
    G = np.abs(np.fft.rfft(g - g.mean()))
    gf = np.fft.rfftfreq(len(g), 1 / fsd)
    band = (gf >= lo_b) & (gf <= min(0.45 * fsd, hi_b))
    if band.sum() < 8:
        return None, 0.0
    ref = np.median(G[band]) + 1e-12
    k = int(np.argmax(np.where(band, G, 0)))
    f, strength = gf[k], G[k] / ref
    for div in (2, 3):                       # prefer the fundamental over a harmonic
        kk = int(np.argmin(np.abs(gf - f / div)))
        if band[kk] and G[kk] > 0.7 * G[k] and G[kk] / ref > 6:
            f, strength = gf[kk], G[kk] / ref
            break
    return (float(f) if strength > 6 else None), float(strength)


def _msk_lines(z, fsd, lo_b, hi_b):
    """MSK signature: squaring the signal gives exactly two strong lines, one baud apart and symmetric about
    twice the centre frequency. FSK gives several lines, PSK one, so neither passes."""
    q = z ** 2
    Q = np.abs(np.fft.fft(q * np.hanning(len(q))))
    qf = np.fft.fftfreq(len(q), 1 / fsd)
    ref = np.median(Q) + 1e-12
    peaks = []
    for k in np.argsort(-Q)[:40]:
        if all(abs(qf[k] - qf[j]) > 0.6 for j in peaks):
            peaks.append(k)
        if len(peaks) == 3:
            break
    if len(peaks) < 3:
        return None
    a, b, c = (Q[k] for k in peaks)
    if a / ref < 25 or b < 0.4 * a or c > 0.4 * b:
        return None
    sep = abs(qf[peaks[0]] - qf[peaks[1]])
    mid = (qf[peaks[0]] + qf[peaks[1]]) / 2
    if lo_b <= sep <= hi_b and abs(mid) < 0.25 * sep:
        return float(sep), float(b / ref)
    return None


def _keyed_fine(seg, f0, bw):
    """On/off keying (CW) from a 5 ms band envelope."""
    if len(seg) < FS // 2:
        return False
    X = np.fft.rfft(seg)
    fr = np.fft.rfftfreq(len(seg), 1 / FS)
    X[(fr < f0 - bw / 2) | (fr > f0 + bw / 2)] = 0
    y = np.fft.irfft(X, len(seg))
    env = np.sqrt(np.convolve(y ** 2, np.ones(240) / 240, mode="same"))[::60]    # 20 ms average, 5 ms steps
    lo, hi = np.percentile(env, 15), np.percentile(env, 92)
    if hi < 3 * lo:
        return False
    on = env > lo + 0.4 * (hi - lo)
    if on.all() or not on.any() or np.median(env[on]) < 4 * np.median(env[~on]):
        return False                         # Morse is clearly on or off (12 dB or more between the two)
    runs_on = [n * 0.005 for _, n in _runs(on)]
    runs_off = [n * 0.005 for s, n in _runs(~on) if 0 < s]
    # Morse elements last 40-500 ms; PSK31's envelope dips (every 32 ms) are far shorter
    return (len(runs_on) >= 5 and 0.2 < on.mean() < 0.85 and 0.035 <= np.median(runs_on) < 0.5
            and len(runs_off) >= 4 and 0.035 <= np.median(runs_off) < 0.6)


def _psk_score(seg, f0, bw):
    """Strength of 31.25 Hz amplitude dips (PSK31) in a band around f0."""
    if len(seg) < FS:
        return 0.0
    X = np.fft.rfft(seg)
    fr = np.fft.rfftfreq(len(seg), 1 / FS)
    X[(fr < f0 - bw) | (fr > f0 + bw)] = 0
    z = np.abs(np.fft.irfft(X, len(seg)))
    E = np.abs(np.fft.rfft(z - z.mean()))
    ef = np.fft.rfftfreq(len(z), 1 / FS)
    k = int(np.argmin(np.abs(ef - 31.25)))
    ref = np.median(E[(ef > 10) & (ef < 60)]) + 1e-9
    return float(E[k - 2:k + 3].max() / ref)


def _syllabic(e, hop_s):
    """Share of envelope variation at 2-8 Hz (speech rhythm)."""
    if len(e) < 32:
        return 0.0
    E = np.abs(np.fft.rfft(e - e.mean())) ** 2
    fr = np.fft.rfftfreq(len(e), hop_s)
    return float(E[(fr >= 2) & (fr <= 8)].sum() / (E[fr > 0.3].sum() + 1e-12))


def _features(x, R, b0, b1, df, hop_s, noise_hr):
    nb = b1 - b0 + 1
    e = R[:, b0:b1 + 1].mean(axis=1)
    thr = 1.0 + 4.0 / math.sqrt(nb) + 0.6
    raw = e > thr
    on = _close_gaps(raw, int(0.35 / hop_s))
    runs = [r for r in _runs(on) if r[1] * hop_s >= 0.25]
    if not runs:
        return None
    s, n = max(runs, key=lambda r: e[r[0]:r[0] + r[1]].sum())
    # significance: excess energy over the run compared with what noise alone would give
    z = (e[s:s + n].mean() - 1.0) * math.sqrt(nb * n * 0.06)     # frames overlap 8.5x: few independent cells
    if z < 6:
        return None
    f = {"start_s": s * hop_s, "dur_s": n * hop_s, "on_frac": float(on.mean()), "z": float(z),
         "cut_start": s == 0, "cut_end": s + n >= len(on) - 1}
    # keying: look across the whole active span (gaps up to 1.5 s), counting on/off changes
    span = _close_gaps(raw, int(1.5 / hop_s))
    sr = max(_runs(span), key=lambda r: r[1])
    inner = raw[sr[0]:sr[0] + sr[1]]
    on_runs = [r[1] * hop_s for r in _runs(inner)]
    coarse = bool(len(on_runs) >= 4 and 0.2 < inner.mean() < 0.85 and np.median(on_runs) < 0.6)
    f["keyed"] = False
    # energy-based extent: the cumulative excess energy of a steady signal rises linearly from start to end,
    # so its 5 % and 95 % points give start and length even when a weak signal breaks into pieces
    c = np.cumsum(np.clip(e - 1.0, -1, None))
    if c[-1] > 0:
        q05, q95 = np.searchsorted(c, 0.05 * c[-1]), np.searchsorted(c, 0.95 * c[-1])
        dur_e = (q95 - q05) / 0.9
        st_e = max(0.0, q05 - 0.05 * dur_e)
        if dur_e > 1.25 * max(n, sr[1]) and dur_e * hop_s > 3:
            s, n = int(st_e), int(min(len(e) - st_e, dur_e))
            sr = (s, n)
            f["start_s"], f["dur_s"] = s * hop_s, n * hop_s
            f["cut_start"], f["cut_end"] = s <= 1, s + n >= len(e) - 2
    if sr[1] > n and inner.mean() >= 0.3:        # weak signals break into pieces: measure the whole span
        s, n = sr
        f["start_s"], f["dur_s"] = s * hop_s, n * hop_s
        f["cut_start"], f["cut_end"] = s == 0, s + n >= len(on) - 1
    env = e[s:s + n]
    f["env_cv"] = float(np.std(env) / (np.mean(env) + 1e-9))
    seg = x[int(s * hop_s * FS):int((s + n) * hop_s * FS) + 4096]
    # bandwidth from a fine averaged spectrum: -10 dB width of the excess over the noise
    lo_hz, hi_hz = (b0 - 2) * df, (b1 + 2) * df
    hr = len(seg) >= 3 * 16384 and (hi_hz - lo_hz) < 80
    nfft = 16384 if hr else 4096
    P = _welch(seg, nfft)
    N = noise_hr[nfft]
    dfp = FS / nfft
    k0, k1 = max(0, int(lo_hz / dfp)), min(len(P) - 1, int(hi_hz / dfp) + 1)
    ex = np.maximum(P[k0:k1 + 1] / N[k0:k1 + 1] - 1.0, 0)
    if ex.max() <= 0:
        return None
    occ = np.where(ex > 0.1 * ex.max())[0]
    f["bw"] = float(max(dfp, (occ[-1] - occ[0] + 1) * dfp - (dfp if not hr else 0)))
    w = ex[occ[0]:occ[-1] + 1]
    f["center"] = float((k0 + occ[0] + np.sum(np.arange(len(w)) * w) / (w.sum() + 1e-12)) * dfp)
    f["snr_db"] = float(10 * math.log10(max(ex.sum() * dfp, 1e-6) / 2500.0))
    # two strong peaks inside one region (FSK shift visible in the spectrum)
    pk = _peaks(np.convolve(ex, np.ones(3) / 3, mode="same"), rel=0.25, min_sep=max(2, int(60 / dfp)))
    pk = sorted(pk, key=lambda i: -ex[i])[:2]
    f["shift"] = float(abs(pk[0] - pk[1]) * dfp) if len(pk) == 2 else None
    if f["bw"] < 60 or coarse:                   # fine 5 ms envelope: Morse dots and gaps are ~50-150 ms
        span_seg = x[int(sr[0] * hop_s * FS):int((sr[0] + sr[1]) * hop_s * FS) + 4096]
        k = _keyed_fine(span_seg, f["center"], max(f["bw"], 20) + 30)
        if k:
            f["keyed"] = True
            f["start_s"], f["dur_s"] = sr[0] * hop_s, sr[1] * hop_s
            seg = span_seg
    f["baud"], f["baud_strength"] = _baud(seg, f["center"], f["bw"])
    f["ratio"] = f["bw"] / f["baud"] if f["baud"] else None
    f["psk"] = _psk_score(seg, f["center"], max(f["bw"], 30)) if 20 <= f["bw"] <= 120 else 0.0
    f["syll"] = _syllabic(e, hop_s) if f["bw"] > 600 else 0.0
    return f


# --------------------------------------------------------------------------- scoring
def _sim(x, mu, rel):
    if x is None or mu is None:
        return None
    return math.exp(-0.5 * ((x - mu) / (rel * mu)) ** 2)


def _slot_fit(t_abs, sig):
    if t_abs is None or sig.period is None:
        return None
    d = (t_abs - sig.offset) % sig.period
    d = min(d, sig.period - d)
    return math.exp(-0.5 * (d / 0.8) ** 2)


def _score(f, sig, t_abs):
    terms, why = [], []

    def add(v, w, text=None):
        if v is not None:
            terms.append((v, w))
            if v > 0.6 and text:
                why.append(text)

    if sig.baud and f["bw"] <= 1.6 and not f["baud"]:
        add(0.12, 2.0)                           # a single clean line has no sidebands: not a modulated signal
    elif sig.baud:
        if f["baud"]:
            v = _sim(f["baud"], sig.baud, 0.15)
            for h in (0.5, 2.0):                     # a line at half or double the rate: partial credit
                v = max(v, 0.5 * _sim(f["baud"], sig.baud * h, 0.15))
            add(v, 2.0, f"{f['baud']:.2f} baud")
            if sig.ratio and v > 0.6:
                add(_sim(f["ratio"], sig.ratio, 0.35), 1.5,
                    f"about {round(f['ratio'])} tones wide" if sig.ratio >= 3 else "MSK-like spectrum"
                    if sig.family == "pumpkin" else "narrow phase-keyed spectrum")
        else:
            add(0.5, 1.0)                        # rate not measurable (weak signal): rely on the other features
    elif f["baud"] and f["baud_strength"] > 12 and sig.envelope in ("steady", "keyed"):
        add(0.35, 1.0)
    add(_sim(f["bw"], sig.bw, 0.45), 1.0, f"{f['bw']:.0f} Hz wide")
    if sig.dur:
        d = f["dur_s"]
        if f["cut_start"] or f["cut_end"]:
            add(1.0 if sig.dur >= 0.85 * d else _sim(d, sig.dur, 0.2), 1.0, f"lasts at least {d:.0f} s")
        else:
            add(_sim(d, sig.dur, 0.1), 1.5, f"{d:.1f} s long")
    if t_abs is not None and sig.period and not f["cut_start"]:
        add(_slot_fit(t_abs, sig), 1.5, f"starts {sig.offset:g} s into a {sig.period:g} s UTC slot")
    env = {"keyed": 1.0 if f["keyed"] else 0.05,
           "steady": 1.0 if (f["env_cv"] < 0.35 and not f["keyed"]) else 0.1,
           "psk": min(1.0, max(0.05, (f["psk"] - 3) / 5)),
           "syllabic": min(1.0, max(0.05, f["syll"] * 2.5)),
           "burst": 1.0 if f["dur_s"] < 3 else 0.2,
           "constant": 0.1 if f["keyed"] else (0.5 if f["psk"] > 8 else 1.0)}[sig.envelope]
    add(env, 1.5, {"keyed": "keyed on and off", "steady": "steady, unmodulated",
                   "psk": "envelope dips at 31.25 Hz", "syllabic": "speech-like rhythm",
                   "burst": "short burst", "constant": "constant envelope"}[sig.envelope])
    if not terms:
        return 0.0, []
    wsum = sum(w for _, w in terms)
    fit = math.exp(sum(w * math.log(max(v, 1e-4)) for v, w in terms) / wsum)
    return fit, why


_PAIRS = (("RTTY", 150, 188), ("HF packet / APRS 300", 188, 240), ("APRS / packet 1200", 900, 1100))


def _pair_detection(shift, start, dur, center, snr):
    for mode, lo, hi in _PAIRS:
        if lo <= shift <= hi:
            sig = LIB[mode]
            burst = dur < 3
            if sig.envelope == "burst" and not burst:
                continue                              # packets are short bursts
            conf = 0.9 if burst == (sig.envelope == "burst") else 0.4
            return Detection(sig.mode, sig.family, center, shift, conf, start, dur, snr,
                             [f"two tones {shift:.0f} Hz apart", "short burst" if burst else f"{dur:.0f} s continuous"])
    return None


# --------------------------------------------------------------------------- public API
def identify(x, fs=FS, t0=None, fmin=150.0, fmax=3300.0):
    """Signals found in an audio block, best first. t0 = UTC time (time.time()) of the first sample."""
    x = np.asarray(x, dtype=float)
    if fs != FS:
        from scipy.signal import resample_poly
        x = resample_poly(x, FS, fs)
    if len(x) < FS:
        return []
    nfft, hop = 4096, 480
    df, hop_s = FS / nfft, hop / FS
    S = _spectrogram(x, nfft, hop)
    R = S / _noise_floor(S, 151)
    noise_hr = {}
    for n in (4096, 16384):
        Sw = _spectrogram(x if len(x) >= n else np.pad(x, (0, n - len(x))), n, n // 2)
        noise_hr[n] = _noise_floor(Sw, 151 * n // 4096)
    b_lo, b_hi = int(fmin / df), int(fmax / df)
    act = (R[:, b_lo:b_hi] > 4).mean(axis=0)
    level = R[:, b_lo:b_hi].mean(axis=0)
    occupied = _close_gaps((act > 0.06) | (level > 1.25), 3)
    feats = []
    for s0, n0 in _runs(occupied):
        b0, b1 = b_lo + s0, b_lo + s0 + n0 - 1
        f = _features(x, R, max(b0 - 1, 0), b1 + 1, df, hop_s, noise_hr)
        if f:
            feats.append(f)
    out, used = [], set()
    # packets are confirmed by decoding them (CRC-checked), the surest signature of all
    from . import aprs_rx
    for hf, mode, lo_hz, hi_hz in ((False, "APRS / packet 1200", 900, 2500), (True, "HF packet / APRS 300", 1300, 2100)):
        try:
            frames = aprs_rx.decode_audio(x, FS, hf=hf)
        except Exception:                         # noqa: BLE001
            frames = []
        pk = [p for p in (aprs_rx.parse_frame(fr) for fr in frames) if p]
        if pk:
            sig = LIB[mode]
            out.append(Detection(mode, sig.family, (lo_hz + hi_hz) / 2 if not hf else 1700, hi_hz - lo_hz, 1.0, 0.0,
                                 len(x) / FS, 0.0, [f"decoded {len(pk)} packet(s): " + ", ".join(
                                     sorted({p['source'] for p in pk})), sig.note],
                                 {"calls": sorted({p["source"] for p in pk})}))
            used |= {i for i, f in enumerate(feats) if f["dur_s"] < 3}      # the bursts and their splatter
    alone = {}
    for i, f in enumerate(feats):                 # how well each region fits a single-signal signature
        t_abs = (t0 + f["start_s"]) if t0 is not None else None
        alone[i] = max(_score(f, sig, t_abs)[0] for sig in LIBRARY if sig.mode not in [m for m, _, _ in _PAIRS])
    for i, a in enumerate(feats):                 # two-tone FSK seen as two separate regions
        for j in range(i + 1, len(feats)):
            b = feats[j]
            if i in used or j in used or abs(a["start_s"] - b["start_s"]) > 0.6:
                continue
            if max(alone[i], alone[j]) >= 0.55 or abs(a["dur_s"] - b["dur_s"]) > 0.3 * max(a["dur_s"], b["dur_s"]):
                continue
            d = _pair_detection(abs(b["center"] - a["center"]), min(a["start_s"], b["start_s"]),
                                max(a["dur_s"], b["dur_s"]), (a["center"] + b["center"]) / 2, max(a["snr_db"], b["snr_db"]))
            if d:
                out.append(d)
                used |= {i, j}
    for i, f in enumerate(feats):
        if i in used:
            continue
        if f["shift"] and f["bw"] > 120:          # two-tone FSK inside one region
            d = _pair_detection(f["shift"], f["start_s"], f["dur_s"], f["center"], f["snr_db"])
            if d:
                out.append(d)
                continue
        t_abs = (t0 + f["start_s"]) if t0 is not None else None
        scored = sorted(((*_score(f, sig, t_abs), sig) for sig in LIBRARY if sig.mode not in dict(
            (m, 1) for m, _, _ in _PAIRS)), key=lambda r: -r[0])
        (fit, why, sig), second = scored[0], scored[1][0]
        conf = fit * (1.0 - 0.5 * (second / (fit + 1e-9)) ** 4)
        mode, family = (sig.mode, sig.family) if conf >= 0.35 else ("Unknown", "")
        if mode == "Unknown":
            why = [f"{f['bw']:.0f} Hz wide", f"{f['dur_s']:.1f} s"] + ([f"{f['baud']:.1f} baud"] if f["baud"] else [])
        out.append(Detection(mode, family, f["center"], f["bw"], round(conf, 2), f["start_s"], f["dur_s"],
                             round(f["snr_db"], 1), why,
                             {k: (round(float(v), 3) if isinstance(v, (float, np.floating)) else v)
                              for k, v in f.items()}))
    out.sort(key=lambda d: -d.confidence)
    return out


LIB = {s.mode: s for s in LIBRARY}


class Memory:
    """Context over time: the same signal on the same frequency again raises confidence."""

    def __init__(self, keep_s=600, tol_hz=15):
        self.keep_s, self.tol = keep_s, tol_hz
        self.items = []                       # (time, mode, freq)

    def update(self, detections, now=None):
        now = now or time.time()
        self.items = [i for i in self.items if now - i[0] < self.keep_s]
        for d in detections:
            if d.mode == "Unknown":
                continue
            n = sum(1 for t, m, f in self.items if m == d.mode and abs(f - d.freq_hz) < self.tol)
            if n:
                d.seen = n + 1
                d.confidence = round(1 - (1 - d.confidence) * 0.7 ** n, 2)
                d.reasons.append(f"seen {n + 1} times in {self.keep_s // 60} min")
            self.items.append((now, d.mode, d.freq_hz))
        return detections
