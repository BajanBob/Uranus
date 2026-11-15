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
        from . import spectrum
        from .audiodev import resolve
        dev = resolve(device, "in")
        n = int(seconds * fs)
        chunks, got, done = [], [0], threading.Event()

        def cb(data, frames, t, status):
            block = data[:, 0].copy()
            chunks.append(block)
            got[0] += len(block)
            if fs == spectrum.FS:
                spectrum.publish(block)          # live waterfall from the same audio
            if got[0] >= n:
                done.set()
        spectrum.external(True)
        try:
            with sd.InputStream(samplerate=fs, channels=1, dtype="float32", device=dev, blocksize=600, callback=cb):
                done.wait(seconds + 10)
        finally:
            spectrum.external(False)
        x = np.concatenate(chunks) if chunks else np.zeros(0)
        return np.pad(x, (0, max(0, n - len(x))))[:n].astype(float)
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
    def __init__(self, cfg, reporter=None, spot_path=spots.DEFAULT_PATH, on_event=None):
        st, rx = cfg["station"], cfg.get("receive", {})
        self.call, self.grid = st["callsign"], st["grid"]
        self.mode = {"urc": "pumpkin"}.get(rx.get("mode", "pumpkin"), rx.get("mode", "pumpkin"))
        default = {"pumpkin": "PUMPKIN-60", "cucumber": "CUCUMBER-60", "ft8": "FT8", "wspr": "WSPR",
                   "aprs": "APRS"}.get(self.mode, "UR-60")
        self.submode = rx.get("submode", default)
        if self.mode in ("ft8", "wspr", "aprs"):
            self.submode = self.mode.upper()
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
        self.on_event = on_event or (lambda e: None)
        self.stop = threading.Event()
        self.aprs_tail = np.zeros(0)
        self.aprs_seen = {}
        if self.mode == "ft8":
            from . import wsjt
            wsjt.decoder_path("jt9")                    # fail early with a clear message
            self.T, self.period, self.frame_s = 0.16, 15, 13.8 - 4.5   # records 13.8 s from the slot start
        elif self.mode == "wspr":
            from . import wsjt
            wsjt.decoder_path("wsprd")
            self.T, self.period, self.frame_s = 0.683, 120, 114.0 - 4.5
        elif self.mode == "aprs":
            self.T, self.period, self.frame_s = 1 / 1200, 10, 10.0 - 4.5   # continuous, 10-second blocks
        elif self.mode == "pumpkin":
            self.T, self.period = pumpkin.SUBMODES[self.submode], pumpkin.PERIODS[self.submode]
            self.frame_s = pumpkin.NSYM * self.T
        elif self.mode == "cucumber":
            self.T, self.period = cucumber.SUBMODES[self.submode], cucumber.PERIODS[self.submode]
            self.frame_s = cucumber.NSYM * self.T
        else:
            self.T, self.period = urmode.SUBMODES[self.submode], urmode.PERIODS[self.submode]
            self.frame_s = urmode.NSYM * self.T

    def decode(self, x):
        if self.mode in ("ft8", "wspr"):
            from . import wsjt
            fn = wsjt.ft8_decode if self.mode == "ft8" else wsjt.wspr_decode
            res = fn(x, self.dial_hz)
            for r in res:
                r["kind"] = "station" if r["call"] and r["grid"] else "message"
            return self.mode.upper(), res
        if self.mode == "aprs":
            from . import aprs_rx, geo
            block = np.concatenate([self.aprs_tail, x])
            self.aprs_tail = x[-int(1.5 * FS):]           # keep 1.5 s so packets across blocks are caught
            now, res = time.time(), []
            for fr in aprs_rx.decode_audio(block, FS):
                if now - self.aprs_seen.get(fr, 0) < 30:
                    continue
                self.aprs_seen[fr] = now
                pkt = aprs_rx.parse_frame(fr)
                if not pkt:
                    continue
                pos = aprs_rx.position(pkt)
                grid = geo.latlon_to_grid(*pos) if pos else ""
                res.append({"call": pkt["source"], "grid": grid, "snr": 0.0, "freq_hz": int(self.dial_hz),
                            "message": f"{pkt['source']}>{pkt['dest']}: {pkt['info'][:60]}",
                            "kind": "station" if grid else "message", "lat_lon": pos})
            return "APRS", res
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

    def _info(self):
        return {"submode": self.submode, "dial_hz": self.dial_hz, "period": self.period,
                "rec_s": self.frame_s + 4.5}

    def run(self, slots=None, until=None):
        """Decode slot after slot. With `until` (a time.time() value), stop before a slot that would not
        finish in time; the beacon uses this to listen in the gaps between its own transmissions."""
        log.info("Listening for %s on %.4f MHz dial (+%d Hz), %s slots",
                 self.submode, self.dial_hz / 1e6, self.f0, self.period)
        n = 0
        while not self.stop.is_set() and (slots is None or n < slots):
            rec_s = self.frame_s + 4.5
            if self.mode == "aprs":
                start = time.time()                       # APRS packets come at any time: listen continuously
                if until is not None:
                    rec_s = min(rec_s, until - start - 0.5)
                    if rec_s < 3:
                        break
            else:
                start = math.ceil(time.time() / self.period) * self.period
                if until is not None and start + rec_s + 1.0 > until:
                    break
                self.on_event({"type": "waiting", "start": start, **self._info()})
            lead = 0.0 if self.mode in ("ft8", "wspr", "aprs") else 0.3   # WSJT-X decoders expect slot-aligned audio
            while not self.stop.is_set() and time.time() < start - lead:
                self.stop.wait(min(0.5, max(0.01, start - lead - time.time())))
            if self.stop.is_set():
                break
            self.on_event({"type": "recording", "start": start, "end": start + rec_s, **self._info(), "rec_s": rec_s})
            if self.source == "rtl_fm":
                x = sdr.rtl_record(rec_s, self.dial_hz, self.rtl_ppm, self.rtl_gain)
            else:
                x = record(rec_s, self.device)
            self.on_event({"type": "decoding", "start": start, **self._info()})
            level_db = float(20 * np.log10(np.sqrt(np.mean(np.square(x))) + 1e-9)) if len(x) else -120.0
            try:
                mode, res = self.decode(x)
            except Exception as e:                         # noqa: BLE001 - keep listening
                log.warning("decoder error: %s", e)
                mode, res = self.mode.upper(), []
            for r in res:
                if r.get("kind") == "message":
                    log.info("%s %+.0f dB  %s", mode, r["snr"], r["message"])
                    self.on_event({"type": "message", "mode": mode, "snr": r["snr"], "text": r["message"],
                                   "call": r.get("call"), "freq_hz": r["freq_hz"], "start": start})
                    continue
                if r.get("kind") == "text":
                    log.info("TEXT  [%d%s] %r  %+.1f dB", r["seq"], "+" if r["more"] else "", r["text"], r["snr"])
                    self.on_event({"type": "text", "text": r["text"], "snr": r["snr"], "mode": mode, "start": start})
                    continue
                extra = {k: r[k] for k in ("fade_db", "spread_hz") if k in r}
                sp = spots.add({"call": r["call"], "grid": r["grid"], "snr": r["snr"], "freq_hz": r["freq_hz"],
                                "mode": mode, "direction": "rx", "slot": int(start), **extra}, self.spot_path)
                log.info("DECODE %s %s %+.1f dB  %.6f MHz%s", r["call"], r["grid"], r["snr"], r["freq_hz"] / 1e6,
                         f"  {r['message']}" if r.get("message") else "")
                self.on_event({"type": "decode", "spot": sp, "message": r.get("message", "")})
                if self.reporter and mode != "APRS":       # APRS belongs on APRS-IS, not PSK Reporter
                    self.reporter.add(sp)
            if not res and self.mode != "aprs":
                log.info("slot %s: no decode", time.strftime("%H:%M:%S", time.gmtime(start)))
            self.on_event({"type": "result", "start": start, "count": len(res), "level_db": level_db,
                           **self._info()})
            n += 1
