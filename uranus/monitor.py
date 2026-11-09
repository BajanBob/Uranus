"""Listen mode: record each URC/UR slot from the rig, decode, log and report.

Each period the listener records from the period boundary for the frame
length plus a margin, decodes, writes spots to out/spots.jsonl, and hands
them to PSK Reporter if enabled. Audio comes from `sounddevice` when
installed (Windows, Linux, Pi) or from `arecord` (Linux/Pi).
"""

import logging
import math
import shutil
import subprocess
import tempfile
import threading
import time
import os
import wave

import numpy as np

from . import spots, urcoherent, urmode

log = logging.getLogger("uranus.listen")
FS = 12000


def record(seconds, device="default", fs=FS):
    try:
        import sounddevice as sd
        dev = None if device in ("", "default") else (int(device) if str(device).isdigit() else device)
        x = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype="float32", device=dev, blocking=True)
        return x[:, 0].astype(float)
    except ImportError:
        pass
    if not shutil.which("arecord"):
        raise RuntimeError("no audio input: pip install sounddevice, or install alsa-utils (arecord)")
    path = os.path.join(tempfile.gettempdir(), f"uranus_rx_{os.getpid()}.wav")
    subprocess.run(["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(fs), "-c", "1",
                    "-d", str(int(math.ceil(seconds))), path], check=True, timeout=seconds + 15)
    with wave.open(path) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
    os.unlink(path)
    return x


class Listener:
    def __init__(self, cfg, reporter=None, spot_path=spots.DEFAULT_PATH):
        st, rx = cfg["station"], cfg.get("receive", {})
        self.call, self.grid = st["callsign"], st["grid"]
        self.mode = rx.get("mode", "urc")
        self.submode = rx.get("submode", "URC-60" if self.mode == "urc" else "UR-60")
        self.dial_hz = float(rx.get("dial_mhz", 144.490)) * 1e6
        self.f0 = float(rx.get("audio_offset_hz", st.get("audio_offset_hz", 1500)))
        self.device = rx.get("audio_device", "default")
        self.reporter = reporter
        self.spot_path = spot_path
        self.stop = threading.Event()
        if self.mode == "urc":
            self.T, self.period = urcoherent.SUBMODES[self.submode], urcoherent.PERIODS[self.submode]
            self.frame_s = urcoherent.NSYM * self.T
        else:
            self.T, self.period = urmode.SUBMODES[self.submode], urmode.PERIODS[self.submode]
            self.frame_s = urmode.NSYM * self.T

    def decode(self, x):
        if self.mode == "urc":
            res = urcoherent.decode_audio(x, self.submode, f_nom=self.f0, df_max=0.1 / self.T)
            mode = "URC"
            for r in res:
                r["freq_hz"] = int(self.dial_hz + self.f0 + r.get("df", 0))
        else:
            res = urmode.decode_audio(x, self.submode)
            mode = "UR"
            for r in res:
                r["freq_hz"] = int(self.dial_hz + r.get("freq", self.f0))
        return mode, res

    def run(self, slots=None):
        log.info("Listening for %s on %.4f MHz dial (+%d Hz), %s slots",
                 self.submode, self.dial_hz / 1e6, self.f0, self.period)
        n = 0
        while not self.stop.is_set() and (slots is None or n < slots):
            start = math.ceil(time.time() / self.period) * self.period
            while not self.stop.is_set() and time.time() < start - 0.3:
                self.stop.wait(min(0.5, start - 0.3 - time.time()))
            if self.stop.is_set():
                break
            x = record(self.frame_s + 4.5, self.device)
            mode, res = self.decode(x)
            for r in res:
                sp = spots.add({"call": r["call"], "grid": r["grid"], "snr": r["snr"], "freq_hz": r["freq_hz"],
                                "mode": mode, "direction": "rx", "slot": int(start)}, self.spot_path)
                log.info("DECODE %s %s %+.1f dB  %.6f MHz", r["call"], r["grid"], r["snr"], r["freq_hz"] / 1e6)
                if self.reporter:
                    self.reporter.add(sp)
            if not res:
                log.info("slot %s: no decode", time.strftime("%H:%M:%S", time.gmtime(start)))
            n += 1
