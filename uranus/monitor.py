"""Listen mode: record each Pumpkin, Cucumber or UR slot, decode, log and report.

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

from . import cucumber, sdr, spots, pumpkin, urmode

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
        self.mode = {"urc": "pumpkin"}.get(rx.get("mode", "pumpkin"), rx.get("mode", "pumpkin"))
        default = {"pumpkin": "PUMPKIN-60", "cucumber": "CUCUMBER-60"}.get(self.mode, "UR-60")
        self.submode = rx.get("submode", default)
        if self.submode.startswith("URC-"):
            self.submode = "PUMPKIN-" + self.submode.split("-")[1]
        if self.mode == "cucumber" and not self.submode.startswith("CUCUMBER-"):
            self.submode = "CUCUMBER-" + self.submode.split("-")[1]
        self.dial_hz = float(rx.get("dial_mhz", 144.490)) * 1e6
        self.f0 = float(rx.get("audio_offset_hz", st.get("audio_offset_hz", 1500)))
        self.device = rx.get("audio_device", "default")
        self.source = rx.get("source", "audio")
        self.rtl_ppm, self.rtl_gain = rx.get("rtl_ppm", 0), rx.get("rtl_gain", 40)
        self.reporter = reporter
        self.spot_path = spot_path
        self.stop = threading.Event()
        if self.mode == "pumpkin":
            self.T, self.period = pumpkin.SUBMODES[self.submode], pumpkin.PERIODS[self.submode]
            self.frame_s = pumpkin.NSYM * self.T
        elif self.mode == "cucumber":
            self.T, self.period = cucumber.SUBMODES[self.submode], cucumber.PERIODS[self.submode]
            self.frame_s = cucumber.NSYM * self.T
        else:
            self.T, self.period = urmode.SUBMODES[self.submode], urmode.PERIODS[self.submode]
            self.frame_s = urmode.NSYM * self.T

    def decode(self, x):
        if self.mode == "pumpkin":
            res = pumpkin.decode_audio(x, self.submode, f_nom=self.f0, df_max=0.1 / self.T)
            mode = "PUMPKIN"
            for r in res:
                r["freq_hz"] = int(self.dial_hz + self.f0 + r.get("df", 0))
        elif self.mode == "cucumber":
            res = cucumber.decode_audio(x, self.submode)
            mode = "CUCUMBER"
            for r in res:
                r["freq_hz"] = int(self.dial_hz)          # FM channel frequency
                r["snr"] = r["audio_snr"]                 # audio SNR after the FM detector
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
            if self.source == "rtl_fm":
                x = sdr.rtl_record(self.frame_s + 4.5, self.dial_hz, self.rtl_ppm, self.rtl_gain)
            else:
                x = record(self.frame_s + 4.5, self.device)
            mode, res = self.decode(x)
            for r in res:
                if r.get("kind") == "text":
                    log.info("TEXT  [%d%s] %r  %+.1f dB", r["seq"], "+" if r["more"] else "", r["text"], r["snr"])
                    continue
                extra = {k: r[k] for k in ("fade_db", "spread_hz") if k in r}
                sp = spots.add({"call": r["call"], "grid": r["grid"], "snr": r["snr"], "freq_hz": r["freq_hz"],
                                "mode": mode, "direction": "rx", "slot": int(start), **extra}, self.spot_path)
                log.info("DECODE %s %s %+.1f dB  %.6f MHz", r["call"], r["grid"], r["snr"], r["freq_hz"] / 1e6)
                if self.reporter:
                    self.reporter.add(sp)
            if not res:
                log.info("slot %s: no decode", time.strftime("%H:%M:%S", time.gmtime(start)))
            n += 1
