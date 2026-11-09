"""Keyboard chat over Pumpkin (SSB) or Cucumber (FM).

Each transmission carries one frame: either an ID frame (your callsign and
grid, message type 6 = "chat ID") or a text frame of 11 characters. A
message is split into text frames with a sequence number and a "more
follows" flag, and the receiver joins them back together.

Stations take turns, as in FT8: one sends in even slots and listens in odd
slots, the other does the opposite. An ID frame goes out before your first
message and again whenever `id_every_s` has passed (10 minutes by default),
so your callsign is sent regularly as identification rules require. Text is
never encrypted.

Speed: about 11 characters per transmission. That is about 44 characters a
minute on PUMPKIN-15 or CUCUMBER-15, and about 11 a minute on the -60
submodes, which are the more sensitive ones.
"""

import collections
import logging
import math
import threading
import time

import numpy as np

from . import cucumber, monitor, propagation, pumpkin, sdr, urmode

log = logging.getLogger("uranus.chat")
ID_TYPE = 6

SUBMODES = list(pumpkin.SUBMODES)[:3] + list(cucumber.SUBMODES)[:3]   # 15/30/60 s of each


def mode_of(submode):
    return "cucumber" if submode.startswith("CUCUMBER") else "pumpkin"


def period_of(submode):
    return int(submode.split("-")[1])


def frames_for(text, call, grid, send_id):
    """List of (label, bits) frames for one chat message."""
    out = []
    if send_id:
        out.append(("ID " + call, urmode.pack_message(call, grid, ID_TYPE, 0)))
    parts = urmode.split_text(text)
    for i, p in enumerate(parts):
        out.append((f"TEXT {p.strip()!r}", urmode.pack_text(p, i % 5, i < len(parts) - 1)))
    return out


class Reassembler:
    """Joins text frames back into messages and remembers who sent them (last ID heard)."""

    def __init__(self, id_memory_s=900):
        self.buf, self.expect, self.last_id, self.id_memory_s = [], 0, None, id_memory_s

    def feed(self, m, now=None):
        """Returns a list of events for one decoded frame."""
        now = now or time.time()
        ev = []
        if m.get("kind") == "beacon":
            self.last_id = (m["call"], m["grid"], now)       # any beacon or ID names the sender
            ev.append({"type": "id", "call": m["call"], "grid": m["grid"], "snr": m.get("snr")})
            return ev
        sender = self.last_id[0] if self.last_id and now - self.last_id[2] < self.id_memory_s else "?"
        ev.append({"type": "frame", "text": m["text"], "seq": m["seq"], "more": m["more"], "from": sender,
                   "snr": m.get("snr")})
        if m["seq"] == 0 and self.buf:
            ev.append({"type": "message", "from": sender, "text": "".join(self.buf).strip() + " [...]", "complete": False})
            self.buf = []
        if m["seq"] != self.expect % 5 and self.buf:
            self.buf.append(" [...] ")
        self.buf.append(m["text"])
        self.expect = m["seq"] + 1
        if not m["more"]:
            ev.append({"type": "message", "from": sender, "text": "".join(self.buf).strip(), "complete": True})
            self.buf, self.expect = [], 0
        return ev


class ChatEngine:
    def __init__(self, cfg, radio, submode="PUMPKIN-15", freq_mhz=144.495, tx_parity=0,
                 on_event=None, id_every_s=600):
        st = cfg["station"]
        self.call, self.grid = st["callsign"], st["grid"]
        self.cfg, self.radio = cfg, radio
        self.submode, self.mode = submode, mode_of(submode)
        self.period = period_of(submode)
        self.freq_hz = freq_mhz * 1e6
        self.lo_hz = self._lo_for(freq_mhz) * 1e6
        self.f0 = float(st.get("audio_offset_hz", 1500))
        self.tx_parity = tx_parity
        self.on_event = on_event or (lambda e: log.info("%s", e))
        self.id_every_s = id_every_s
        self.queue = collections.deque()
        self.last_id_sent = 0.0
        self.re = Reassembler()
        self.stop = threading.Event()
        rx = cfg.get("receive", {})
        self.source, self.device = rx.get("source", "audio"), rx.get("audio_device", "default")
        self.rtl = (rx.get("rtl_ppm", 0), rx.get("rtl_gain", 40))
        T = (cucumber if self.mode == "cucumber" else pumpkin).SUBMODES[submode]
        self.T = T
        self.frame_s = pumpkin.NSYM * T

    def _lo_for(self, freq_mhz):
        band = propagation.band_of(freq_mhz * 1e6)
        for b in self.cfg.get("band", []):
            if b.get("name") == band:
                return float(b.get("transverter_lo_mhz", 0.0))
        return 0.0

    def send(self, text):
        need_id = time.time() - self.last_id_sent > self.id_every_s
        fr = frames_for(text, self.call, self.grid, need_id)
        if need_id:
            self.last_id_sent = time.time()
        self.queue.extend(fr)
        n_tx = len(fr)
        self.on_event({"type": "queued", "text": " ".join(urmode.split_text(text)), "frames": n_tx,
                       "eta_s": n_tx * 2 * self.period})
        return n_tx

    def _audio(self, bits):
        sym = pumpkin.message_to_symbols(None, None, bits=bits)
        if self.mode == "cucumber":
            return cucumber.modulate(sym, self.submode), cucumber.FS
        return pumpkin.modulate(sym, self.submode, f0=self.f0), pumpkin.FS

    def _decode(self, x):
        if self.mode == "cucumber":
            res = cucumber.decode_audio(x, self.submode)
            for r in res:
                r["snr"] = r.get("audio_snr")
            return res
        return pumpkin.decode_audio(x, self.submode, f_nom=self.f0, df_max=0.1 / self.T)

    def _record(self):
        if self.source == "rtl_fm":
            return sdr.rtl_record(self.frame_s + 4.5, self.freq_hz, *self.rtl)
        return monitor.record(self.frame_s + 4.5, self.device)

    def _sleep_until(self, t):
        while not self.stop.is_set() and time.time() < t:
            self.stop.wait(min(0.5, t - time.time()))

    def run(self):
        rig_mode = "FM" if self.mode == "cucumber" else self.cfg.get("rig_modes", {}).get("pumpkin", "USB")
        self.radio.tune(self.freq_hz - self.lo_hz, rig_mode)
        self.on_event({"type": "status", "text": f"Chat on {self.freq_hz / 1e6:.4f} MHz, {self.submode}, "
                       f"sending in {'even' if self.tx_parity == 0 else 'odd'} slots"})
        while not self.stop.is_set():
            idx = math.floor(time.time() / self.period) + 1
            start = idx * self.period
            tx = idx % 2 == self.tx_parity and self.queue
            if tx:
                if time.time() - self.last_id_sent > self.id_every_s and self.queue[0][0][:2] != "ID":
                    self.queue.appendleft(("ID " + self.call, urmode.pack_message(self.call, self.grid, ID_TYPE, 0)))
                    self.last_id_sent = time.time()
                label, bits = self.queue[0]
                audio, fs = self._audio(bits)
                self._sleep_until(start + 1.0)
                if self.stop.is_set():
                    break
                self.queue.popleft()
                self.on_event({"type": "tx", "text": label, "left": len(self.queue)})
                self.radio.transmit(self.freq_hz - self.lo_hz, rig_mode, audio, fs, "chat")
            else:
                self._sleep_until(start - 0.3)
                if self.stop.is_set():
                    break
                try:
                    x = self._record()
                except Exception as e:           # noqa: BLE001
                    self.on_event({"type": "error", "text": f"receive failed: {e}"})
                    self.stop.wait(self.period)
                    continue
                for m in self._decode(x):
                    for ev in self.re.feed(m):
                        self.on_event(ev)


def demo(text, submode="PUMPKIN-15", level_db=-20.0, call="8P5AB", grid="GK03", seed=None):
    """Send a message through a simulated channel and decode it: no radio needed.
    level_db is SNR in 2500 Hz for Pumpkin, carrier-to-noise in 12.5 kHz for Cucumber."""
    rng = np.random.default_rng(seed)
    re_ = Reassembler()
    events = []
    for label, bits in frames_for(text, call, grid, True):
        sym = pumpkin.message_to_symbols(None, None, bits=bits)
        if mode_of(submode) == "cucumber":
            a = np.concatenate([np.zeros(12000), cucumber.modulate(sym, submode).astype(float), np.zeros(6000)])
            res = cucumber.decode_audio(cucumber.fm_channel(a, level_db, rng), submode)
            for r in res:
                r["snr"] = r.get("audio_snr")
        else:
            y = pumpkin.modulate(sym, submode).astype(float)
            x = np.concatenate([np.zeros(12000), y, np.zeros(6000)])
            x += np.sqrt(np.mean(y ** 2) / (10 ** (level_db / 10) * 2500 * 2 / pumpkin.FS)) * rng.standard_normal(len(x))
            res = pumpkin.decode_audio(x, submode, df_max=0.1 / pumpkin.SUBMODES[submode])
        events.append({"type": "tx", "text": label})
        if not res:
            events.append({"type": "lost", "text": label})
        for m in res:
            events.extend(re_.feed(m))
    return events
