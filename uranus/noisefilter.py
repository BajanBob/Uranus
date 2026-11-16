"""Receive noise filter for local interference such as laptop chargers and switch-mode power supplies.

Applied to each recorded slot before decoding (FT8, FT4, WSPR, APRS, Pumpkin, UR, AUTO). Three stages:

1. Hum cut      - high-pass below 150 Hz (mains / ground-loop hum and its low harmonics; no mode uses it).
2. Line notcher  (below) runs first, then
3. Impulse blanker - zeroes short clicks and buzz pulses that stand far above the local level. Measured
                  against a running median, so steady signals - even very strong ones - are never touched.
   Line notcher - learns narrow lines that sit on the same audio frequency slot after slot (a charger's
                  whistles and "birdies") and removes them with deep notch filters. A real station only qualifies if it sends on one
                  frequency for several slots in a row without a gap; FT8 / FT4 / WSPR / Pumpkin stations do
                  not, so their signals pass. Up to MAX_LINES lines, each about 6 Hz wide.

Software cannot remove broadband noise that covers the same frequencies as the signal: that has to be
stopped at the source (ferrites, a cleaner supply, battery). See docs/NOISE.md.
"""

import numpy as np

NFFT = 4096                   # 2.93 Hz bins at 12 kHz
MAX_LINES = 24
LINE_DB = 10.0                # a line must stand this far above the local noise floor ...
LINE_SLOTS = 4                # ... in this many slots in a row, present most of each slot


class NoiseFilter:
    def __init__(self, fs=12000, hum=True, blanker=True, notch=True):
        self.fs, self.hum, self.blanker, self.notch = fs, hum, blanker, notch
        self.count = None             # per-bin: consecutive slots with a steady line here
        self.lines = np.zeros(0, int)
        self.stats = {"blanked_pct": 0.0, "lines": 0}

    # -------------------------------------------------------------- stages
    def _highpass(self, x):
        from scipy.signal import butter, sosfiltfilt
        sos = butter(4, 150, "highpass", fs=self.fs, output="sos")
        return sosfiltfilt(sos, x) if len(x) > 50 else x

    def _blank(self, x, k=6.0, block=120):
        n = len(x) // block * block
        if n < block * 8:
            return x, 0.0
        a = np.abs(x[:n]).reshape(-1, block)
        med = np.median(a, axis=1)                     # level of each 10 ms block
        from scipy.ndimage import median_filter
        ref = median_filter(med, size=31, mode="nearest") * 1.4826 + 1e-12   # running noise sigma (~0.3 s)
        thr = np.repeat(k * ref, block)
        thr = np.concatenate([thr, np.full(len(x) - n, thr[-1])])
        hit = np.abs(x) > thr
        if not hit.any():
            return x, 0.0
        g = int(0.00025 * self.fs) + 1                  # blank 0.25 ms either side of each click
        mask = np.convolve(hit.astype(float), np.ones(2 * g + 1), "same") > 0
        frac = mask.mean()
        if frac > 0.35:                                 # not impulsive noise: leave alone
            return x, 0.0
        y = x.copy()
        y[mask] = 0.0
        return y, float(frac)

    def _find_lines(self, x):
        from scipy.ndimage import median_filter
        from scipy.signal import stft
        _, _, Z = stft(x, self.fs, nperseg=NFFT, noverlap=NFFT // 2, boundary=None)
        P = np.abs(Z) ** 2
        if P.shape[1] < 3:
            return
        floor = median_filter(np.median(P, axis=1), size=41, mode="nearest") + 1e-20
        steady = np.mean(P > floor[:, None] * 10 ** (LINE_DB / 10), axis=1) > 0.9   # there ~all slot long
        if self.count is None or len(self.count) != len(steady):
            self.count = np.zeros(len(steady), int)
        self.count = np.where(steady, self.count + 1, 0)
        cand = np.where(self.count >= LINE_SLOTS)[0]
        cand = cand[(cand * self.fs / NFFT > 100)]
        if len(cand) > MAX_LINES:
            cand = cand[np.argsort(-np.median(P[cand], axis=1))[:MAX_LINES]]
        self.lines = np.sort(cand)

    def _clusters(self):
        """Group neighbouring line bins into (centre_hz, width_hz) whistles."""
        out, run = [], []
        for b in self.lines:
            if run and b - run[-1] > 2:
                out.append(run)
                run = []
            run.append(int(b))
        if run:
            out.append(run)
        df = self.fs / NFFT
        return [((r[0] + r[-1]) / 2 * df, (r[-1] - r[0]) * df + 4 * df) for r in out]

    def _notch(self, x):
        if not len(self.lines):
            return x
        from scipy.signal import iirnotch, sosfiltfilt, tf2sos
        for f0, bw in self._clusters():
            if not 0 < f0 < self.fs / 2 - bw:
                continue
            b, a = iirnotch(f0, max(1.0, f0 / bw), fs=self.fs)
            x = sosfiltfilt(tf2sos(b, a), x)              # zero-phase, deep at the whistle
        return x

    # -------------------------------------------------------------- public
    def clean(self, x):
        x = np.asarray(x, float)
        if len(x) < self.fs:
            return x
        if self.hum:
            x = self._highpass(x)
        frac = 0.0
        if self.notch:                                  # whistles first, so they don't hide the clicks
            self._find_lines(x)
            x = self._notch(x)
        if self.blanker:
            x, frac = self._blank(x)
        self.stats = {"blanked_pct": round(100 * frac, 2), "lines": int(len(self.lines)),
                      "line_hz": [round(float(b * self.fs / NFFT)) for b in self.lines]}
        return x

    def describe(self):
        s = self.stats
        parts = []
        if s.get("blanked_pct"):
            parts.append(f"blanked {s['blanked_pct']:.1f}% clicks")
        if s.get("lines"):
            hz = ", ".join(str(h) for h in s["line_hz"][:6]) + ("…" if s["lines"] > 6 else "")
            parts.append(f"notched {s['lines']} whistle(s) at {hz} Hz")
        return "noise filter: " + ("; ".join(parts) if parts else "nothing to remove")
