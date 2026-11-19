"""HF weather fax (WEFAX / radiofax) receiver.

Marine weather charts are sent as FM on a 1900 Hz audio subcarrier: 1500 Hz is black, 2300 Hz is white. Almost
all HF stations use 120 lines a minute with an index of cooperation (IOC) of 576, so a line takes 0.5 s and is
pi x 576 = 1809 pixels wide. A chart starts with 5 s of start tone (black/white alternating 300 times a second),
then about 30 s of phasing lines (one short pulse per line that marks the line start), then the picture, and ends
with 5 s of stop tone (450 times a second).

Published frequencies are the "assigned" ones: with an SSB radio, set USB 1.9 kHz lower (the "carrier"
frequency) and the subcarrier lands at 1900 Hz audio.

Decoder: mix the audio down by 1900 Hz, low-pass, measure the instantaneous frequency (FM discriminator), turn
1500..2300 Hz into black..white, look for the start and stop tones, then cut the brightness into 0.5 s lines.
The phasing pulse is found by averaging the phasing lines, and every line is shifted so the pulse sits at the
left edge. A sound card whose clock is off by N parts per million slants the chart; `ppm` corrects it.
"""
import datetime as _dt
import os

import numpy as np

FS = 12000
LPM, IOC = 120, 576
WIDTH = int(round(np.pi * IOC))           # 1809 pixels a line
BLACK, WHITE = 1500.0, 2300.0
CENTRE = 1900.0
START_HZ, STOP_HZ = 300.0, 450.0          # IOC 576 start / stop modulation
START_288_HZ = 675.0                      # IOC 288 start tone (stop is 450 Hz for both)
LPM_CHOICES = (60, 90, 100, 120, 180, 240)
OFFSET_KHZ = 1.9                          # USB dial = assigned frequency - 1.9 kHz
MAX_LINES = 1800                          # 15 minutes: longer than any chart, then save anyway

# name, call, assigned kHz (the dial is 1.9 kHz lower), note.  Sources: NOAA/NWS "Worldwide Marine Radiofacsimile
# Broadcast Schedules" and the USCG; most are 120 LPM / IOC 576. Schedules change: check weather.gov/marine.
STATIONS = [
    ("New Orleans", "NMG", 4317.9, "Gulf of Mexico, Caribbean, tropical Atlantic; 00-09, 12-21 UTC"),
    ("New Orleans", "NMG", 8503.9, "Gulf of Mexico, Caribbean, tropical Atlantic"),
    ("New Orleans", "NMG", 12789.9, "Gulf of Mexico, Caribbean, tropical Atlantic"),
    ("New Orleans", "NMG", 17146.4, "daytime only, 12-21 UTC"),
    ("Boston", "NMF", 4235.0, "North Atlantic; night (about 02-10 UTC)"),
    ("Boston", "NMF", 6340.5, "North Atlantic"),
    ("Boston", "NMF", 9110.0, "North Atlantic"),
    ("Boston", "NMF", 12750.0, "North Atlantic; daytime (about 14-22 UTC)"),
    ("Point Reyes", "NMC", 4346.0, "North and East Pacific"),
    ("Point Reyes", "NMC", 8682.0, "North and East Pacific"),
    ("Point Reyes", "NMC", 12786.0, "North and East Pacific"),
    ("Point Reyes", "NMC", 17151.2, "North and East Pacific"),
    ("Point Reyes", "NMC", 22527.0, "North and East Pacific; daytime"),
    ("Kodiak", "NOJ", 2054.0, "Gulf of Alaska"),
    ("Kodiak", "NOJ", 4298.0, "Gulf of Alaska"),
    ("Kodiak", "NOJ", 8459.0, "Gulf of Alaska"),
    ("Kodiak", "NOJ", 12412.5, "Gulf of Alaska"),
    ("Honolulu", "KVM70", 9982.5, "Central and South Pacific; night"),
    ("Honolulu", "KVM70", 11090.0, "Central and South Pacific"),
    ("Honolulu", "KVM70", 16135.0, "Central and South Pacific; day"),
    ("Halifax", "CFH", 4271.0, "Canadian Atlantic"),
    ("Halifax", "CFH", 6496.4, "Canadian Atlantic"),
    ("Halifax", "CFH", 10536.0, "Canadian Atlantic"),
    ("Halifax", "CFH", 13510.0, "Canadian Atlantic"),
    ("Hamburg", "DDH3", 3855.0, "North Sea, Baltic, North Atlantic"),
    ("Hamburg", "DDK3", 7880.0, "North Sea, Baltic, North Atlantic"),
    ("Hamburg", "DDK6", 13882.5, "North Sea, Baltic, North Atlantic"),
    ("Tokyo", "JMH", 3622.5, "North-west Pacific"),
    ("Tokyo", "JMH", 7795.0, "North-west Pacific"),
    ("Tokyo", "JMH", 13988.5, "North-west Pacific"),
    ("Wiluna", "VMW", 7535.0, "Australia"),
    ("Wiluna", "VMW", 10555.0, "Australia"),
    ("Wiluna", "VMW", 15615.0, "Australia"),
]


def frequencies(call):
    return sorted(st[2] for st in STATIONS if st[1] == call)


def pick(call, daytime):
    """Autopilot frequency: by day the highest 10-22 MHz channel, at night the lowest 3-10 MHz one
    (falling back to the nearest the station has)."""
    fs = frequencies(call)
    if not fs:
        return None
    if daytime:
        day = [f for f in fs if 10000 <= f <= 22000]
        return max(day) if day else max(fs)
    night = [f for f in fs if 3000 <= f <= 10000]
    return min(night) if night else min(fs)


def next_frequency(call, current_khz):
    """The station's next channel after this one (wraps), for hopping when nothing is heard."""
    fs = frequencies(call)
    if not fs:
        return None
    later = [f for f in fs if f > current_khz + 0.05]
    return later[0] if later else fs[0]


def dial_mhz(assigned_khz):
    """USB dial for an assigned (published) WEFAX frequency."""
    return round((assigned_khz - OFFSET_KHZ) / 1000.0, 6)


def station_label(st):
    name, call, khz, note = st
    return f"{call:<6}{khz:>9.1f} kHz  {name} · {note}"


# ------------------------------------------------------------------ test signal
def encode(image, fs=FS, lpm=LPM, start_s=5.0, phasing_lines=40, stop_s=5.0, f_err_hz=0.0, ioc=IOC):
    """WEFAX audio for an image (rows x cols, 0 = black, 1 = white): start tone, phasing, picture, stop tone.
    Used by the tests and the demo."""
    img = np.clip(np.asarray(image, float), 0, 1)
    spl = fs * 60.0 / lpm
    lum = []
    n = int(start_s * fs)
    lum.append((np.arange(n) * 2 * (START_HZ if ioc == 576 else START_288_HZ) / fs).astype(int) % 2 * 1.0)
    pulse = int(0.05 * spl)                                       # phasing: white line, 5 % black pulse
    for k in range(phasing_lines):
        a, b = int(round(k * spl)), int(round((k + 1) * spl))
        line = np.ones(b - a)
        line[:pulse] = 0
        lum.append(line)
    base = phasing_lines * spl
    for k, row in enumerate(img):
        a, b = int(round(base + k * spl)), int(round(base + (k + 1) * spl))
        lum.append(np.interp(np.linspace(0, len(row) - 1, b - a), np.arange(len(row)), row))
    n = int(stop_s * fs)
    lum.append((np.arange(n) * 2 * STOP_HZ / fs).astype(int) % 2 * 1.0)
    lum.append(np.zeros(int(2 * fs)))
    lum = np.concatenate(lum)
    f = BLACK + (WHITE - BLACK) * lum + f_err_hz
    return 0.5 * np.sin(2 * np.pi * np.cumsum(f) / fs)


# ------------------------------------------------------------------ demodulator
class Discriminator:
    """Streaming FM discriminator around 1900 Hz: audio block in, brightness 0..1 out (same rate)."""

    def __init__(self, fs=FS, bw=1000.0, taps=97):
        self.fs = fs
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(2 * bw / 2 / fs * n) * np.hamming(taps)
        self.h = h / h.sum()
        self.tail = np.zeros(taps - 1, complex)
        self.n0 = 0
        self.prev = 1 + 0j

    def __call__(self, x):
        return np.clip((self.freq(x) - BLACK) / (WHITE - BLACK), 0, 1)

    def freq(self, x):
        """Instantaneous frequency of the audio, Hz."""
        x = np.asarray(x, float)
        t = (self.n0 + np.arange(len(x))) / self.fs
        self.n0 += len(x)
        z = np.concatenate([self.tail, x * np.exp(-2j * np.pi * CENTRE * t)])
        self.tail = z[-(len(self.h) - 1):]
        y = np.convolve(z, self.h, mode="valid")
        y = np.where(np.abs(y) < 1e-12, 1e-12, y)
        prev = np.concatenate([[self.prev], y[:-1]])
        self.prev = y[-1]
        return CENTRE + np.angle(y * np.conj(prev)) * self.fs / (2 * np.pi)


def tone_power(lum, fs, hz):
    """Share (0..1) of the brightness variation that alternates at `hz`: about 0.8 during a start or stop
    tone, near 0 for pictures, phasing lines and noise."""
    v = np.asarray(lum, float) - np.mean(lum)
    if len(v) < fs // 4:
        return 0.0
    s = np.abs(np.fft.rfft(v * np.hanning(len(v)))) ** 2
    k = int(round(hz * len(v) / fs))
    w = max(2, int(round(3.0 * len(v) / fs)))                 # +-3 Hz
    return float(s[max(1, k - w):k + w + 1].sum() / (s[1:].sum() + 1e-12))


# ------------------------------------------------------------------ receiver
class Receiver:
    """Feed it audio blocks; it finds the start tone, phases, builds the chart line by line and saves a PNG
    when the stop tone comes (or after 15 minutes). `on_line(row)` gets every new (unphased) line for a live view,
    `on_event(dict)` gets state changes and saved files.

    Automatic settings (the defaults, lpm=None and ioc=None):
      * IOC from the start tone: 300 Hz = IOC 576, 675 Hz = IOC 288
      * tuning error: the start tone swings between black and white, so its average shows how far the radio
        is off; black and white are moved to match (up to +-250 Hz)
      * LPM: the first 12 seconds of the picture are tested for the line period that repeats best
        (60, 90, 100, 120, 180 or 240 lines a minute)
      * a chart joined without its start tone gets its black and white levels from the signal itself."""

    MEASURE_S = 12.0

    def __init__(self, fs=FS, ppm=0.0, outdir=None, label="wefax", on_line=None, on_event=None, auto_start=True,
                 lpm=None, ioc=None):
        self.fs, self.ppm = fs, float(ppm)
        self.outdir = outdir or os.path.join(os.path.expanduser("~"), "Uranus", "wefax")
        self.label = label
        self.on_line = on_line or (lambda row: None)
        self.on_event = on_event or (lambda e: None)
        self.auto_start = auto_start
        self.auto_lpm, self.auto_ioc = lpm is None, ioc is None
        self.lpm, self.ioc = int(lpm or LPM), int(ioc or IOC)
        self.disc = Discriminator(fs)
        self.wide = Discriminator(fs, bw=1900.0)    # tones and tuning error: passes the 675 Hz start tone
        self.offset = 0.0
        self.reset()

    @property
    def spl(self):
        return self.fs * 60.0 / self.lpm * (1 + self.ppm * 1e-6)

    @property
    def width(self):
        return int(round(np.pi * self.ioc))

    @property
    def black(self):
        return BLACK + self.offset

    @property
    def white(self):
        return WHITE + self.offset

    def _lum(self, f):
        return np.clip((f - self.black) / (self.white - self.black), 0, 1)

    def reset(self):
        self.state = "idle"                          # idle -> start -> image -> (saved) idle
        self.buf = np.zeros(0)                       # brightness waiting to become lines
        self.win = np.zeros(0)                       # last second of brightness, for tone detection
        self.fwin = np.zeros(0)                      # last second of frequency, for the tuning error
        self.hits = {"start": 0, "start288": 0, "stop": 0}
        self.lines, self.phase = [], None
        self.pos = 0.0                               # fractional line position within buf
        self.mbuf, self.locked, self.from_tone = [], not self.auto_lpm, False
        self.saved = []

    # -- control
    def start_now(self):
        """Begin a chart immediately (joining one already in progress: the left edge may be off)."""
        self.from_tone = False
        self._begin(phased=False)

    def finish(self):
        """Save what has been received so far."""
        if self.state == "image" and not self.locked and self.mbuf:
            self._lock()
        if self.state == "image" and len(self.lines) > 20:
            return self._save()
        self.state = "idle"
        return None

    def _begin(self, phased=True):
        self.state = "image"
        self.lines, self.phase, self.buf, self.pos = [], (None if phased else 0), np.zeros(0), 0.0
        self.mbuf, self.locked = [], not self.auto_lpm
        self.t_start = _dt.datetime.now(_dt.timezone.utc)
        self.on_event({"type": "start", "phased": phased})
        if self.locked:
            self._mode_event()

    def _mode_event(self):
        self.on_event({"type": "mode", "lpm": self.lpm, "ioc": self.ioc, "offset_hz": round(self.offset),
                       "auto": self.auto_lpm or self.auto_ioc})

    # -- audio in
    def feed(self, x):
        f = self.disc.freq(x)
        fw = self.wide.freq(x)
        self.win = np.concatenate([self.win, np.clip((fw - BLACK) / (WHITE - BLACK), -0.5, 1.5)])[-self.fs:]
        self.fwin = np.concatenate([self.fwin, fw])[-self.fs:]
        self.nwin = np.concatenate([getattr(self, "nwin", np.zeros(0)), self._lum(f)])[-self.fs:]
        self.xwin = np.concatenate([getattr(self, "xwin", np.zeros(0)), np.asarray(x, float)])[-self.fs:]
        if len(self.win) >= self.fs:
            # 300 / 450 Hz tones: the narrow discriminator is quieter; 675 Hz needs the wide one
            s576 = tone_power(self.nwin, self.fs, START_HZ) > 0.06 or tone_power(self.win, self.fs, START_HZ) > 0.06
            s288 = tone_power(self.win, self.fs, START_288_HZ) > 0.06 and not s576
            stop = tone_power(self.nwin, self.fs, STOP_HZ) > 0.06 or tone_power(self.win, self.fs, STOP_HZ) > 0.06
            for k, on in (("start", s576), ("start288", s288), ("stop", stop)):
                self.hits[k] = self.hits[k] + len(x) if on else 0
            if self.state == "idle" and self.auto_start and max(self.hits["start"], self.hits["start288"]) >= 1.5 * self.fs:
                if self.auto_ioc:
                    self.ioc = 576 if self.hits["start"] >= self.hits["start288"] else 288
                off = tone_offset(self.xwin, self.fs)
                if off is not None:                  # the tone sits on black and white: their midpoint
                    self.offset = off
                self.state, self.from_tone = "start", True
                self.on_event({"type": "start_tone", "ioc": self.ioc, "offset_hz": round(self.offset)})
            elif self.state == "start" and not (s576 or s288):
                self._begin(phased=True)
                f = f[-max(1, min(len(f), len(x))):]   # begin cutting lines from here
            elif self.state == "image" and self.hits["stop"] >= 1.5 * self.fs:
                self._take(f)
                if not self.locked:
                    self._lock()
                del self.lines[-int(2.5 * self.fs / self.spl) - 1:]     # stop tone heard so far
                return self._save()
        if self.state == "image":
            self._take(f)
            if len(self.lines) >= 15 * self.lpm:
                return self._save()
        return None

    def _take(self, f):
        if self.locked:
            self._cut(self._lum(f))
            return
        self.mbuf.append(np.asarray(f, float))
        if sum(len(b) for b in self.mbuf) >= self.MEASURE_S * self.fs:
            self._lock()

    def _lock(self):
        """Settle the automatic settings from the first seconds of the picture, then cut it into lines."""
        f = np.concatenate(self.mbuf) if self.mbuf else np.zeros(0)
        self.mbuf, self.locked = [], True
        if not self.from_tone and len(f) > self.fs:      # no start tone heard: black and white from the signal
            ff = f[np.abs(f - CENTRE) < 700]
            if len(ff) > self.fs:
                lo, hi = np.percentile(ff, 3), np.percentile(ff, 97)
                if 250 < hi - lo < 1100:
                    self.offset = float(np.clip((lo + hi) / 2 - CENTRE, -250, 250))
        lum = self._lum(f)
        if self.auto_lpm and len(lum) >= 4 * self.fs:
            self.lpm = detect_lpm(lum, self.fs)
        self._mode_event()
        self._cut(lum)

    def _cut(self, lum):
        self.buf = np.concatenate([self.buf, lum])
        spl, width = self.spl, self.width
        while self.pos + spl <= len(self.buf):
            a = self.pos
            seg = self.buf[int(a):int(a + spl)]
            edges = np.linspace(0, len(seg), width + 1).astype(int)
            row = np.add.reduceat(seg, edges[:-1]) / np.maximum(1, np.diff(edges))
            self.lines.append(row.astype(np.float32))
            self.pos += spl
            if self.phase is None and len(self.lines) == 24:
                self.phase = find_phase(self.lines[4:24])
                self.on_event({"type": "phased", "phase_px": self.phase})
            self.on_line(row)                    # raw: shift by -self.phase to display (phase settles at line 24)
        drop = int(self.pos) - 1
        if drop > 0:
            self.buf, self.pos = self.buf[drop:], self.pos - drop

    def _shift(self, row):
        return np.roll(row, -(self.phase or 0))

    def image(self):
        """The chart so far as an 8-bit array (lines x width), phased; phasing lines are left out."""
        if not self.lines:
            return np.zeros((0, self.width), np.uint8)
        rows = np.array([self._shift(r) for r in self.lines])
        keep = [i for i, r in enumerate(rows) if not _is_phasing(r)]
        if keep:
            rows = rows[keep[0]:]
        return (np.clip(rows, 0, 1) * 255).astype(np.uint8)

    def _save(self):
        img = self.image()
        self.state = "idle"
        self.hits = {"start": 0, "start288": 0, "stop": 0}
        if len(img) < 20:
            self.on_event({"type": "discarded", "lines": len(img)})
            return None
        os.makedirs(self.outdir, exist_ok=True)
        stamp = getattr(self, "t_start", _dt.datetime.now(_dt.timezone.utc)).strftime("%Y%m%d_%H%M")
        path = os.path.join(self.outdir, f"{self.label}_{stamp}Z_{self.lpm}lpm.png")
        save_png(path, img)
        self.saved.append(path)
        self.on_event({"type": "saved", "path": path, "lines": len(img)})
        return path


def tone_offset(x, fs=FS):
    """Tuning error from a start tone: its spectrum is symmetric about the fax centre (1900 Hz when tuned
    right), so the centroid of the audio power above the noise floor, 1100-2700 Hz, is the centre."""
    x = np.asarray(x, float)
    if len(x) < fs // 2:
        return None
    p = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / fs)
    m = (fr > 1100) & (fr < 2700)
    q = np.clip(p[m] - np.median(p[m]) * 1.5, 0, None)
    if q.sum() <= 0:
        return None
    return float(np.clip((fr[m] * q).sum() / q.sum() - CENTRE, -250, 250))


def detect_lpm(lum, fs=FS):
    """Lines a minute: the shortest standard line period at which the picture repeats best. A chart (and
    above all its phasing lines) looks almost the same one line later; at 120 LPM it also repeats after two
    lines, so the shortest strong period wins."""
    v = np.asarray(lum, float)[::12]                # 1 kHz is plenty for line structure
    v = v - v.mean()
    rate = fs / 12
    den = np.dot(v, v) + 1e-12
    score = {}
    for lpm in LPM_CHOICES:
        lag = int(round(rate * 60.0 / lpm))
        if lag >= len(v) // 2:
            continue
        lo, hi = max(1, lag - 3), lag + 4               # small search for sound-card clock error
        score[lpm] = max(np.dot(v[:-k], v[k:]) / den for k in range(lo, hi))
    if not score:
        return LPM
    best = max(score.values())
    return max(l for l, sc in score.items() if sc >= 0.85 * best)   # highest LPM = shortest period


def find_phase(lines):
    """Column where the phasing pulse sits: the column that differs most from the rest of the line, on
    average over the phasing lines (works for a black pulse on white or a white pulse on black)."""
    a = np.array(lines, float)
    WIDTH = a.shape[1]
    dev = np.abs(a - np.median(a, axis=1, keepdims=True)).mean(axis=0)
    k = max(5, int(31 * WIDTH / 1810) | 1)           # pulse is 5 % of a line: smooth to find it
    ext = np.concatenate([dev[-k:], dev, dev[:k]])
    sm = np.convolve(ext, np.ones(k) / k, mode="same")[k:-k]
    c = int(np.argmax(sm))
    half = 0.5 * dev[np.arange(c - 10, c + 11) % WIDTH].mean()
    i = c                                           # walk left to the pulse's leading edge
    while dev[(i - 1) % WIDTH] > half and c - i < WIDTH // 4:
        i -= 1
    return i % WIDTH


def _is_phasing(row):
    dark = np.mean(row < 0.3)
    return 0.02 < dark < 0.10 or 0.90 < dark < 0.98


def save_png(path, img):
    """Grey PNG without needing Pillow (Pillow is used when present, for smaller files)."""
    try:
        from PIL import Image
        Image.fromarray(img, "L").save(path, optimize=True)
        return
    except ImportError:
        pass
    import struct
    import zlib
    h, w = img.shape
    raw = b"".join(b"\x00" + img[i].tobytes() for i in range(h))

    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def decode(x, fs=FS, ppm=0.0, block=1200):
    """Decode a whole recording (tests, or a saved WAV). Returns the Receiver (its .saved PNG paths, .image())."""
    import tempfile
    rx = Receiver(fs, ppm=ppm, outdir=tempfile.mkdtemp(prefix="uranus_wefax_"))
    for i in range(0, len(x), block):
        rx.feed(x[i:i + block])
    if rx.state == "image":
        rx.finish()
    return rx
