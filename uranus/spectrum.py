"""Live audio spectrum and waterfall of the receiver passband.

The radio's receive audio (e.g. the IC-9100's USB Audio CODEC) covers about
0-3 kHz above the dial frequency: the band segment where FT8, WSPR, Pumpkin
and Cucumber tones sit. This module turns that audio into waterfall rows.

While listen mode is recording, it publishes its audio here, so the device is
opened only once. At other times the waterfall opens the input itself.
"""

import logging
import threading
import time

import numpy as np

log = logging.getLogger("uranus.spectrum")

FS = 12000
NFFT = 2048                  # 5.86 Hz bins
HOP = 1500                   # 8 rows a second
F_MAX = 3000.0

_subs = set()
_lock = threading.Lock()
_external = 0                # number of active publishers (listen mode recording)


def subscribe(fn):
    with _lock:
        _subs.add(fn)


def unsubscribe(fn):
    with _lock:
        _subs.discard(fn)


def publish(x):
    """Audio block (mono float, FS) from another reader, e.g. listen mode."""
    with _lock:
        subs = list(_subs)
    for fn in subs:
        try:
            fn(x)
        except Exception:                        # noqa: BLE001
            pass


def external(active):
    """Listen mode calls external(True) while it records and external(False) after."""
    global _external
    with _lock:
        _external = max(0, _external + (1 if active else -1))


def external_active():
    return _external > 0


class Analyzer:
    """Feeds audio, produces spectrum rows (dB per bin from 0 to F_MAX) through on_row."""

    def __init__(self, on_row):
        self.on_row = on_row
        self.buf = np.zeros(0)
        self.win = np.hanning(NFFT)
        self.nbins = int(F_MAX / (FS / NFFT))

    def feed(self, x):
        self.buf = np.concatenate([self.buf, np.asarray(x, dtype=float)])
        while len(self.buf) >= NFFT:
            seg = self.buf[:NFFT]
            spec = np.abs(np.fft.rfft(seg * self.win))[:self.nbins] ** 2
            self.on_row(10 * np.log10(spec + 1e-12))
            self.buf = self.buf[HOP:]


class Monitor:
    """Owns the waterfall: listens to published audio, and opens the input itself when nobody else is."""

    def __init__(self, device, on_row):
        self.device = device
        self.an = Analyzer(on_row)
        self.stream = None
        self.error = ""
        self.running = False
        self._next_try = 0.0
        subscribe(self.an.feed)

    def start(self):
        self.running = True
        self.tick()

    def tick(self):
        """Call regularly: opens or closes the private stream as listen mode starts and stops."""
        if not self.running:
            return
        if external_active():
            self._close()
        elif self.stream is None and time.time() >= self._next_try:
            self._open()
            if self.stream is None:
                self._next_try = time.time() + 5

    def _open(self):
        try:
            import sounddevice as sd
            from .audiodev import resolve
            dev = resolve(self.device, "in")
            self.stream = sd.InputStream(samplerate=FS, channels=1, dtype="float32", device=dev, blocksize=600,
                                         callback=lambda data, n, t, st: self.an.feed(data[:, 0].copy()))
            self.stream.start()
            self.error = ""
        except Exception as e:                   # noqa: BLE001
            self.stream = None
            self.error = str(e)

    def _close(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:                    # noqa: BLE001
                pass
            self.stream = None

    def stop(self):
        self.running = False
        self._close()
        unsubscribe(self.an.feed)
