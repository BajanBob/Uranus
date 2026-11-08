"""Band/mode sequencer.

Order:  every enabled slot of band 1 (in file order), then band 2, ...,
        then start again.
Gaps:   `gap_between_tx_s` after each transmission inside a band,
        `gap_between_bands_s` after the last transmission of a band.
Timing: FT8 starts 0.5 s after a 15 s boundary, WSPR 1 s after an even UTC
        minute, UR-n on its period boundary + 1 s, APRS immediately.
"""

import datetime as dt
import logging
import os
import math
import random
import subprocess
import threading
import time
import tomllib
from dataclasses import dataclass, field

from . import aprs, urcoherent, urmode, wsjt

log = logging.getLogger("uranus.scheduler")

DURATION = {"ft8": 12.64, "wspr": 110.6}
RIG_MODE_DEFAULT = {"aprs": "FM", "ft8": "USB", "wspr": "USB", "ur": "USB", "urc": "USB"}


@dataclass
class Slot:
    band: str
    mode: str
    freq_mhz: float
    enabled: bool = True
    submode: str = "UR-60"
    msg_type: int = 0
    msg_value: int = 0
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def label(self):
        m = self.submode if self.mode in ("ur", "urc") else self.mode.upper()
        return f"{self.band}_{m}_{self.freq_mhz:.3f}"


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    slots = []
    for band in cfg["band"]:
        for s in band["slot"]:
            known = {k: s[k] for k in ("mode", "freq_mhz", "enabled", "submode",
                                       "msg_type", "msg_value", "note") if k in s}
            slots.append(Slot(band=band["name"], **known))
    st = cfg["station"]
    if st.get("callsign", "N0CALL").upper() in ("N0CALL", "NOCALL", ""):
        raise SystemExit("Set your own callsign in [station] callsign before running.")
    return cfg, slots


def slot_duration(slot, cfg=None):
    if slot.mode == "ur":
        return urmode.NSYM * urmode.SUBMODES[slot.submode]
    if slot.mode == "urc":
        return (urcoherent.NSYM + 1) * urcoherent.SUBMODES[slot.submode]
    if slot.mode == "aprs":
        return 1.2                          # typical; actual length comes from the audio
    return DURATION[slot.mode]


def align(t, slot):
    """Earliest legal start time >= t for this slot."""
    if slot.mode == "aprs":
        return t
    if slot.mode == "ft8":
        period, offset = 15, 0.5
    elif slot.mode == "wspr":
        period, offset = 120, 1.0
    elif slot.mode == "urc":
        period, offset = urcoherent.PERIODS[slot.submode], 1.0
    else:
        period, offset = urmode.PERIODS[slot.submode], 1.0
    start = math.ceil((t - offset) / period) * period + offset
    return start


def bands_of(slots):
    """Group enabled slots by band, keeping file order."""
    bands = []
    for s in slots:
        if s.enabled:
            if not bands or bands[-1][0] != s.band:
                bands.append((s.band, []))
            bands[-1][1].append(s)
    return bands


def gap_after(cfg, band_slots, i):
    t = cfg["timing"]
    return t["gap_between_tx_s"] if i < len(band_slots) - 1 else t["gap_between_bands_s"]


def plan(cfg, slots, start, cycles=1):
    t, events = start, []
    for _ in range(cycles):
        for _, band_slots in bands_of(slots):
            for i, s in enumerate(band_slots):
                begin = align(t, s)
                end = begin + slot_duration(s)
                events.append((begin, end, s))
                t = end + gap_after(cfg, band_slots, i)
    return events


def ntp_ok():
    if os.name == "nt":
        return None                          # check Windows time sync yourself (see README-WINDOWS)
    try:
        r = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "yes"
    except Exception:                        # noqa: BLE001
        return None


class Runner:
    def __init__(self, cfg, slots, radio):
        self.cfg, self.slots, self.radio = cfg, slots, radio
        self.st = cfg["station"]
        self.stop = threading.Event()        # set() to stop between transmissions

    def audio_for(self, s):
        st = self.st
        off = float(st.get("audio_offset_hz", 1500))
        if s.mode == "aprs":
            info = aprs.position_info(st["lat"], st["lon"], st.get("aprs_symbol_table", "/"),
                                      st.get("aprs_symbol", "-"), st.get("aprs_comment", ""))
            src = f"{st['callsign']}-{st.get('aprs_ssid', 0)}" if st.get("aprs_ssid") else st["callsign"]
            path = tuple(p for p in st.get("aprs_path", "WIDE1-1,WIDE2-1").split(",") if p)
            return aprs.packet_audio(src, info, path=path), aprs.FS
        if s.mode == "ft8":
            return wsjt.ft8_audio(f"CQ {st['callsign']} {st['grid']}", off), wsjt.FS
        if s.mode == "wspr":
            return wsjt.wspr_audio(st["callsign"], st["grid"], int(st["wspr_power_dbm"]), off), wsjt.FS
        if s.mode == "urc":
            sym = urcoherent.message_to_symbols(st["callsign"], st["grid"], s.msg_type, s.msg_value)
            return urcoherent.modulate(sym, s.submode, f0=off), urcoherent.FS
        tones = urmode.message_to_tones(st["callsign"], st["grid"], s.msg_type, s.msg_value)
        return urmode.modulate(tones, s.submode, f0=off), urmode.FS

    def run(self, cycles=None):
        if ntp_ok() is False:
            log.warning("System clock is NOT NTP-synchronised: FT8/WSPR/UR will not decode.")
        cs = self.cfg.get("carrier_sense", {})
        rigmodes = {**RIG_MODE_DEFAULT, **self.cfg.get("rig_modes", {})}
        done = 0
        while cycles is None or done < cycles:
            for _, band_slots in bands_of(self.slots):
                for i, s in enumerate(band_slots):
                    if self.stop.is_set():
                        log.info("stopped")
                        return
                    self._one(s, rigmodes, cs)
                    self._sleep_until(time.time() + gap_after(self.cfg, band_slots, i))
            done += 1

    def _one(self, s, rigmodes, cs):
        try:
            audio, fs = self.audio_for(s)
        except Exception as e:               # noqa: BLE001
            log.error("skip %s: %s", s.label, e)
            return
        begin = align(time.time() + 4, s)    # 4 s to tune the rig
        self._sleep_until(begin - 3)
        if self.stop.is_set():
            return
        self.radio.tune(s.freq_mhz * 1e6, rigmodes[s.mode])
        if s.mode == "aprs" and cs.get("enabled", True):
            if not self._clear(cs):
                log.warning("%s: channel busy, skipped", s.label)
                return
        else:
            self._sleep_until(begin)
        log.info("TX %s at %s UTC", s.label,
                 dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3])
        self.radio.transmit(s.freq_mhz * 1e6, rigmodes[s.mode], audio, fs, s.label)

    def _clear(self, cs):
        for _ in range(int(cs.get("retries", 3)) + 1):
            if not self.radio.channel_busy(cs.get("listen_s", 2.0), cs.get("threshold_db", -40)):
                return True
            time.sleep(random.uniform(3, 10))
        return False

    def _sleep_until(self, t):
        while not self.stop.is_set():
            r = t - time.time()
            if r <= 0:
                return
            self.stop.wait(min(r, 0.5) if r > 0.05 else r)
