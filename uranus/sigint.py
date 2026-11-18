"""Signal ID ("SIGINT" identifier): what is that sound in the receiver?

Listens to a block of receive audio and names what is in it, in plain English, with what it is, what it sounds
like, what to do next and where to read more. It combines:

  * the signature finder used by AUTO (signalid): FT8, FT4, WSPR, Q65, JT65, CW, carriers, PSK31, RTTY, packet,
    SSB voice, Pumpkin, UR
  * whole-passband checks of its own: HF weather fax (WEFAX), SITOR-B / NAVTEX (170 Hz FSK at 100 baud) told
    apart from RTTY (45 baud), MIL-STD-188-141 ALE (8 tones, 125 baud), mains hum (50 or 60 Hz harmonics),
    switching-supply combs (chargers, LED drivers), impulse noise (clicks), and a noise-only passband
  * the dial frequency: known users nearby (amateur segments, weather-fax stations, time signals, NAVTEX,
    broadcast bands)

It only identifies signal types. It does not decode or decrypt anyone's traffic beyond the amateur and public
broadcast modes Uranus already decodes.
"""
from dataclasses import dataclass, field

import numpy as np

from . import signalid

FS = 12000
WIKI = "https://www.sigidwiki.com/wiki/"

# name -> (what it is, what it sounds like, what to do, sigidwiki page)
INFO = {
    "FT8": ("WSJT-X weak-signal mode; 15-second slots, the busiest digital mode on HF.",
            "Soft warbling tones that start and stop together every 15 seconds.", "Decode: AUTO or FT8.", "FT8"),
    "FT4": ("WSJT-X contest mode; 7.5-second slots.", "Quick warbles every 7.5 seconds.", "Decode: FT4.", "FT4"),
    "WSPR": ("Weak Signal Propagation Reporter beacon; 2-minute transmissions, 6 Hz wide.",
             "Almost silent: a faint steady whistle lasting nearly two minutes.", "Decode: WSPR.", "WSPR"),
    "Q65": ("WSJT-X deep VHF/EME mode; 60-second slots.", "A slow wandering whistle for 51 seconds.",
            "Decode: Q65.", "Q65"),
    "JT65": ("Older WSJT weak-signal mode; 60-second slots.", "A slow sequence of tones for about 47 seconds.",
             "Decode: JT65.", "JT65"),
    "CW": ("Morse code.", "A single tone keyed in dots and dashes.", "Read it by ear, or note the callsign.",
           "Morse_Code_(CW)"),
    "Carrier": ("An unmodulated tone: a beacon carrier, a tuning signal or an interfering birdie.",
                "A pure steady whistle.", "If it never moves, it may be generated in your own house.", "Carrier"),
    "PSK31": ("BPSK keyboard chat mode, 31 Hz wide.", "A steady tone with a fast gentle warble.",
              "Decode with a PSK31 program (fldigi).", "PSK31"),
    "RTTY": ("Radioteletype: 2-tone FSK, 170 Hz shift, 45.45 baud. Amateur RTTY or weather/news broadcasts.",
             "A steady two-note 'diddle-diddle' warble.", "Decode with fldigi (RTTY 45.45 baud, 170 Hz).",
             "RTTY"),
    "SITOR-B / NAVTEX": ("Maritime text broadcast (NAVTEX, SITOR-B): 2-tone FSK, 170 Hz shift, 100 baud. "
                         "Navigation and weather warnings for ships.",
                         "A fast, buzzy two-tone chirp, quicker than amateur RTTY.",
                         "Decode with a NAVTEX program (fldigi, YaND).", "NAVTEX"),
    "HF packet / APRS 300": ("300-baud AX.25 packet (HF APRS).", "Short buzzy bursts.", "Decode: APRS (HF).",
                             "AX.25"),
    "APRS / packet 1200": ("1200-baud AX.25 packet (VHF APRS).", "Short harsh 'brrrp' bursts.", "Decode: APRS.",
                           "AX.25"),
    "SSB voice": ("Someone talking on single sideband.", "Speech; it sounds like Donald Duck if you are a little "
                  "off frequency.", "Turn the radio's tuning a little until the voice sounds natural.",
                  "Single_Sideband_(SSB)"),
    "WEFAX": ("HF weather fax (radiofax): an FM picture signal between 1500 Hz (black) and 2300 Hz (white), "
              "120 lines a minute.", "A scratchy swish with a steady two-beats-a-second rhythm; a harsh buzz at "
              "the start and a higher buzz at the end of each chart.",
              "Open Weather fax: tune 1.9 kHz below the published frequency on USB.", "Radiofax"),
    "ALE": ("Automatic Link Establishment (MIL-STD-188-141): HF stations sounding and calling each other "
            "automatically. Used by government, military, aid agencies and some radio amateurs.",
            "A short, fast burst of chirping tones, often every few minutes.",
            "Nothing to do; amateur ALE is on HFLink channels such as 14.109.", "MIL-STD-188-141"),
    "Mains hum": ("Hum from the electricity supply, picked up by the radio, the USB audio lead or a ground loop. "
                  "Not a radio signal.", "A low hum or buzz that never changes.",
                  "Run the laptop on battery and see if it goes; add ferrite chokes to the USB and charger leads; "
                  "keep the noise filter on.", "Power_Line_Noise"),
    "Switching-supply comb": ("Interference from a switch-mode power supply: laptop charger, LED lamp, TV or "
                              "solar inverter. Not a radio signal.",
                              "Rough whistles or a raspy buzz at evenly spaced pitches, often drifting.",
                              "Unplug chargers and lamps one by one to find it; fit ferrite chokes.", "Interference"),
    "Impulse noise": ("Clicks from electrical sparks: chargers, motors, thermostats, electric fences, or lightning "
                      "far away.", "Crackles and pops.", "Turn on the radio's noise blanker; Uranus's noise filter "
                      "blanks clicks before decoding.", "Interference"),
    "Noise only": ("Nothing above the band noise.", "A steady hiss.", "Try another frequency, or the scanner.", ""),
    "No radio signals": ("Apart from the interference above, nothing but band noise.", "A hiss behind the noise.",
                         "Cure the interference first; weak signals hide under it.", ""),
}
for _m in list(signalid.LIB):
    if _m.startswith(("PUMPKIN", "UR-")):
        INFO[_m] = ("Uranus weak-signal mode from another Uranus station.", "A faint steady whistle.",
                    "Decode: AUTO or " + _m.split("-")[0] + ".", "")


@dataclass
class Finding:
    name: str
    confidence: float
    freq_hz: float = 0.0              # audio Hz above the dial (0 for the whole passband)
    bw_hz: float = 0.0
    reasons: list = field(default_factory=list)
    kind: str = "signal"              # signal, interference, noise

    @property
    def what(self):
        return INFO.get(self.name, ("", "", "", ""))[0]

    @property
    def sounds(self):
        return INFO.get(self.name, ("", "", "", ""))[1]

    @property
    def action(self):
        return INFO.get(self.name, ("", "", "", ""))[2]

    @property
    def link(self):
        page = INFO.get(self.name, ("", "", "", ""))[3]
        return WIKI + page if page else ""


# ---------------------------------------------------------------- whole-passband measurements
def _psd(x, nfft=16384):
    from scipy.signal import welch
    f, p = welch(x, FS, nperseg=min(nfft, len(x)), noverlap=min(nfft, len(x)) // 2)
    return f, p


def _floor(p, w=301):
    from scipy.ndimage import median_filter
    return median_filter(p, size=w, mode="nearest") + 1e-20


def hum(x):
    """Mains hum: lines at multiples of 50 or 60 Hz (full-wave ripple shows as 100 / 120 Hz)."""
    f, p = _psd(x)
    fl = _floor(p, 151)
    df = f[1] - f[0]
    best = None
    for mains in (50.0, 60.0):
        lines = []
        for k in range(1, 13):
            hz = mains * k
            if hz > 700:
                break
            i = int(round(hz / df))
            seg = p[max(0, i - 2):i + 3]
            db = 10 * np.log10(seg.max() / fl[i])
            if db > 10:
                lines.append((hz, db))
        strong_one = len(lines) == 1 and lines[0][1] > 20 and lines[0][0] in (mains, 2 * mains)
        if (len(lines) >= 2 or strong_one) and (best is None or len(lines) > len(best[1])):
            best = (mains, lines)
    if not best:
        return None
    mains, lines = best
    strongest = max(lines, key=lambda t: t[1])
    conf = min(0.95, 0.45 + 0.1 * len(lines)) if len(lines) > 1 else 0.6
    return Finding("Mains hum", round(conf, 2), strongest[0], 0.0,
                   [f"{len(lines)} line(s) at multiples of {mains:.0f} Hz",
                    f"strongest at {strongest[0]:.0f} Hz, {strongest[1]:.0f} dB above the noise",
                    f"{mains:.0f} Hz mains" + (" (Barbados, UK, Europe)" if mains == 50 else " (Americas)")],
                   "interference")


def comb(x):
    """Evenly spaced narrow lines that are not mains harmonics: a switching power supply."""
    from scipy.signal import find_peaks
    f, p = _psd(x)
    fl = _floor(p, 301)
    band = (f > 200) & (f < 3000)
    db = 10 * np.log10(p / fl)
    idx, _ = find_peaks(np.where(band, db, 0), height=9, distance=int(15 / (f[1] - f[0])))
    if len(idx) < 6:
        return None
    hz = f[idx]
    gaps = np.diff(hz)
    sp = float(np.median(gaps))
    if sp < 25:
        return None
    on = np.abs(gaps / sp - np.round(gaps / sp)) < 0.08
    if on.mean() < 0.75 or abs(sp / 50 - round(sp / 50)) < 0.02 and sp < 400:
        return None
    return Finding("Switching-supply comb", round(min(0.9, 0.4 + 0.05 * len(idx)), 2), float(hz[0]),
                   float(hz[-1] - hz[0]), [f"{len(idx)} narrow lines every {sp:.0f} Hz",
                                           "evenly spaced, not at 50/60 Hz multiples"], "interference")


def impulses(x):
    """Clicks: a very peaky (high-kurtosis) waveform after removing the low hum."""
    from scipy.signal import butter, sosfilt
    y = sosfilt(butter(4, 300, "hp", fs=FS, output="sos"), x)
    s = np.std(y) + 1e-12
    k = float(np.mean((y / s) ** 4))
    if k < 8:
        return None
    big = np.abs(y) > 6 * np.median(np.abs(y)) / 0.6745
    starts = np.flatnonzero(big[1:] & ~big[:-1])
    rate = len(starts) / (len(y) / FS)
    return Finding("Impulse noise", round(min(0.9, 0.3 + k / 40), 2), 0.0, 0.0,
                   [f"peaky waveform (kurtosis {k:.0f}, noise is 3)", f"about {rate:.0f} clicks a second"],
                   "interference")


def wefax_check(x):
    """Weather fax: power concentrated 1500-2300 Hz, FM, and a picture that repeats every 0.5 s line."""
    from . import wefax
    f, p = _psd(x, 4096)
    tot = p[(f > 200) & (f < 3000)].sum() + 1e-20
    share = p[(f > 1450) & (f < 2350)].sum() / tot
    if share < 0.55:
        return None
    lum = wefax.Discriminator(FS)(x)
    reasons = [f"{share:.0%} of the audio between 1500 and 2300 Hz"]
    conf = 0.0
    for hz, what in ((wefax.START_HZ, "start tone (300 Hz)"), (wefax.STOP_HZ, "stop tone (450 Hz)")):
        if wefax.tone_power(lum[-FS:], FS, hz) > 0.2 or wefax.tone_power(lum[:FS], FS, hz) > 0.2:
            conf, reasons = 0.95, reasons + [what + " heard"]
    v = lum[::12] - lum[::12].mean()                    # 1 kHz brightness
    n = len(v)
    if n > 1500:
        ac = np.correlate(v, v, "full")[n - 1:] / (np.dot(v, v) + 1e-12)
        line = ac[480:520].max()                        # one line later (0.5 s)
        off = np.r_[ac[300:380], ac[620:700]].mean()
        if line > 0.25 and line > off + 0.12:
            conf = max(conf, min(0.9, 0.5 + line))
            reasons.append(f"picture repeats line to line every 0.5 s (120 lines a minute, r={line:.2f})")
    if conf < 0.5:
        return None
    return Finding("WEFAX", round(conf, 2), 1900.0, 800.0, reasons)


def _fsk_baud(x, centre, shift):
    """Keying speed of a 2-tone FSK signal: the line in the spectrum of its tone changes."""
    t = np.arange(len(x)) / FS
    z = x * np.exp(-2j * np.pi * centre * t)
    k = int(FS / (shift * 1.2))
    z = np.convolve(z, np.ones(k) / k, mode="same")
    fi = np.angle(z[1:] * np.conj(z[:-1]))
    d = np.abs(np.diff(np.sign(fi)))
    if not d.any():
        return 0.0, 0.0
    D = np.abs(np.fft.rfft(d - d.mean()))
    fr = np.fft.rfftfreq(len(d), 1 / FS)
    m = (fr > 30) & (fr < 320)
    med = np.median(D[m]) + 1e-12
    q = {b: float(D[np.abs(fr - b) < 2].max() / med) for b in (45.45, 50.0, 75.0, 100.0, 150.0, 200.0)}
    qmax = max(q.values())
    i = int(np.argmax(np.where(m, D, 0)))
    if qmax < 3:
        return float(fr[i]), float(D[i] / med)
    b = min(b for b, v in q.items() if v >= 0.5 * qmax)     # the lowest strong line is the keying speed;
    return b, q[b]                                             # the others are its harmonics


def fsk2_check(x):
    """Two-tone FSK teleprinter: RTTY (45/50/75 baud) or SITOR-B / NAVTEX (100 baud), by shift and speed."""
    from scipy.signal import find_peaks
    f, p = _psd(x, 8192)
    df = f[1] - f[0]
    sm = np.convolve(p, np.ones(5) / 5, mode="same")
    db = 10 * np.log10(sm / _floor(sm, 301))
    idx, _ = find_peaks(np.where((f > 250) & (f < 2900), db, 0), height=8, distance=int(60 / df))
    best = None
    for i in idx:
        for j in idx:
            sh = f[j] - f[i]
            if not (150 <= sh <= 195 or 380 <= sh <= 470 or 800 <= sh <= 900):
                continue
            if abs(db[i] - db[j]) > 6 or any(i < k < j for k in idx):
                continue                              # unequal, or another line in between (a comb)
            score = min(db[i], db[j])
            if best is None or score > best[0]:
                best = (score, f[i], f[j], sh)
    if not best:
        return None
    _, lo, hi, sh = best
    baud, q = _fsk_baud(x, (lo + hi) / 2, sh)
    std = [b for b in (45.45, 50.0, 75.0, 100.0, 150.0, 200.0) if abs(baud - b) < 0.07 * b]
    if q < 3 or not std or abs(baud - sh) < 0.1 * sh:
        return None                                   # no keying: two separate carriers beating together
    name = "SITOR-B / NAVTEX" if 90 <= baud <= 110 and sh < 200 else "RTTY"
    return Finding(name, 0.85 if q > 8 else 0.65, float((lo + hi) / 2), float(sh),
                   [f"two tones {sh:.0f} Hz apart ({lo:.0f} / {hi:.0f} Hz)", f"keying at {baud:.0f} baud"])


def ale_check(x):
    """MIL-STD-188-141 ALE: 8 tones from 750 to 2500 Hz, 250 Hz apart, 125 baud."""
    f, p = _psd(x, 4096)
    fl = np.median(p[(f > 300) & (f < 3000)]) + 1e-20
    tones = np.arange(750, 2501, 250)
    lv = np.array([p[np.abs(f - t) < 12].max() / fl for t in tones])
    between = np.array([p[np.abs(f - t) < 12].max() / fl for t in tones[:-1] + 125])
    on = (lv > 6).sum()
    if on < 6 or np.median(lv) < 3 * np.median(between):
        return None
    return Finding("ALE", round(float(min(0.85, 0.35 + 0.06 * on)), 2), 1625.0, 1750.0,
                   [f"{on} of the 8 ALE tones (750-2500 Hz, 250 Hz apart)", "tones far stronger than between them"])


# ---------------------------------------------------------------- frequency context
TIME_STATIONS = [(2.5, "WWV/WWVH time signals"), (5.0, "WWV/WWVH time signals"), (10.0, "WWV/WWVH time signals"),
                 (15.0, "WWV/WWVH time signals"), (20.0, "WWV time signals"), (25.0, "WWV time signals"),
                 (3.330, "CHU Canada time signals"), (7.850, "CHU Canada time signals"),
                 (14.670, "CHU Canada time signals")]
NAVTEX = [(0.518, "NAVTEX (international, English)"), (0.490, "NAVTEX (national language)"),
          (4.2095, "NAVTEX HF")]
BROADCAST = [(3.9, 4.0, "75 m broadcast"), (4.75, 5.06, "60 m tropical broadcast"), (5.9, 6.2, "49 m broadcast"),
             (7.2, 7.45, "41 m broadcast"), (9.4, 9.9, "31 m broadcast"), (11.6, 12.1, "25 m broadcast"),
             (13.57, 13.87, "22 m broadcast"), (15.1, 15.8, "19 m broadcast"), (17.48, 17.9, "16 m broadcast"),
             (21.45, 21.85, "13 m broadcast")]


def context(dial_mhz):
    """Known users near the dial (USB passband dial .. dial + 3 kHz), most specific first."""
    from . import freqplan, wefax
    out = []
    for st in wefax.STATIONS:
        if abs(wefax.dial_mhz(st[2]) - dial_mhz) < 0.0025:
            out.append(f"{st[1]} {st[0]} weather fax, {st[2]:.1f} kHz (dial {wefax.dial_mhz(st[2]):.4f})")
    for mhz, what in TIME_STATIONS + NAVTEX:
        if -0.0035 < mhz - dial_mhz < 0.0035:
            out.append(f"{what} on {mhz:.4f} MHz")
    for o in freqplan.PLAN:
        if abs(o.mhz - dial_mhz) < 0.0015:
            out.append(f"{o.mode.upper()} {o.status}: {o.note}")
    for lo, hi, what in BROADCAST:
        if lo <= dial_mhz <= hi:
            out.append(f"inside the {what} band (AM stations)")
    band = next((b for b, (lo, hi) in freqplan.BAND_EDGES.items() if lo <= dial_mhz <= hi), None)
    if band and not out:
        out.append(f"amateur {freqplan.BAND_NAMES[band]} band")
    if not out:
        out.append("outside the amateur bands (utility / broadcast / maritime users)")
    seen = []
    return [s for s in out if not (s in seen or seen.append(s))]


# ---------------------------------------------------------------- main
def identify(x, fs=FS, dial_hz=0.0, t0=None):
    """Everything recognised in a block of receive audio, best first."""
    x = np.asarray(x, float)
    if fs != FS:
        from scipy.signal import resample_poly
        x = resample_poly(x, FS, fs)
    out = []
    for chk in (hum, comb, impulses, wefax_check, ale_check, fsk2_check):
        if chk is fsk2_check and any(r.name == "Switching-supply comb" and len(r.reasons) and
                                     int(r.reasons[0].split()[0]) >= 10 for r in out):
            continue
        try:
            r = chk(x)
        except Exception:                            # noqa: BLE001 - one check must not stop the others
            r = None
        if r:
            out.append(r)
    names = {r.name for r in out}
    if names & {"WEFAX", "ALE", "RTTY", "SITOR-B / NAVTEX"}:     # data signals make their own line patterns
        out = [r for r in out if r.name != "Switching-supply comb"]
    imp = next((r for r in out if r.name == "Impulse noise"), None)
    if imp:                                          # a regular click train also shows as a comb of lines
        out = [r for r in out if r.name != "Switching-supply comb" or r.confidence > imp.confidence + 0.1]
    whole = {r.name for r in out}
    fsk = next((r for r in out if r.name in ("RTTY", "SITOR-B / NAVTEX")), None)
    for d in signalid.identify(x, FS, t0=t0):
        if d.mode == "Unknown" or d.confidence < 0.35:
            continue
        if "WEFAX" in whole and 1300 < d.freq_hz < 2500:
            continue                                 # pieces of the fax signal
        if "ALE" in whole and 650 < d.freq_hz < 2600:
            continue
        if fsk and abs(d.freq_hz - fsk.freq_hz) < fsk.bw_hz:
            continue                                 # the teleprinter's own tones
        if ("Mains hum" in whole or "Switching-supply comb" in whole) and d.mode == "Carrier":
            continue                                 # the hum / comb lines themselves
        name, reasons = d.mode, list(d.reasons)
        if d.mode == "RTTY":                         # 170 Hz FSK: amateur RTTY or SITOR-B / NAVTEX?
            baud, q = _fsk_baud(x, d.freq_hz, 170.0)
            if q > 4 and 90 <= baud <= 110:
                name = "SITOR-B / NAVTEX"
            if q > 4:
                reasons.append(f"keying at {baud:.0f} baud")
        out.append(Finding(name, d.confidence, d.freq_hz, d.bw_hz, reasons))
    if not [f for f in out if f.kind == "signal"]:
        snr = _band_snr(x)
        if snr < 3:
            out.append(Finding("No radio signals" if out else "Noise only", 0.6, 0.0, 0.0,
                               [f"passband within {snr:.0f} dB of flat noise"], "noise"))
    out.sort(key=lambda f: (f.kind != "signal", -f.confidence))
    return out


def _band_snr(x):
    f, p = _psd(x, 4096)
    b = p[(f > 300) & (f < 2700)]
    return float(10 * np.log10(np.percentile(b, 95) / (np.median(b) + 1e-20)))


def report(findings, dial_mhz=None):
    """Plain-text answer to 'what is this?'."""
    lines = []
    if dial_mhz:
        lines.append(f"Dial {dial_mhz:.4f} MHz: " + "; ".join(context(dial_mhz)))
    if not findings:
        lines.append("Nothing recognised in this recording.")
    for f in findings:
        at = f" at {f.freq_hz:.0f} Hz" if f.freq_hz else ""
        lines.append(f"{f.name}{at} - {f.confidence:.0%}")
        lines.append(f"   What: {f.what}")
        lines.append(f"   Sounds like: {f.sounds}")
        lines.append(f"   Why: {'; '.join(f.reasons[:3])}")
        if f.action:
            lines.append(f"   Next: {f.action}")
        if f.link:
            lines.append(f"   More: {f.link}")
    return "\n".join(lines)
