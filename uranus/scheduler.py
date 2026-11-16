"""Band/mode sequencer.

Order:  every enabled slot of band 1 (in file order), then band 2, ...,
        then start again.
Gaps:   `gap_between_tx_s` after each transmission inside a band,
        `gap_between_bands_s` after the last transmission of a band.
Timing: FT8 starts 0.5 s after a 15 s boundary, FT4 0.5 s after a 7.5 s one, WSPR 1 s after an even UTC
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

from . import aprs, clock, cucumber, pumpkin, urmode, wsjt

log = logging.getLogger("uranus.scheduler")

DURATION = {"ft8": 12.64, "ft4": 5.04, "wspr": 110.6}
RIG_MODE_DEFAULT = {"aprs": "FM", "ft8": "USB", "ft4": "USB", "wspr": "USB", "ur": "USB", "pumpkin": "USB", "cucumber": "FM"}
LEGACY = {"urc": "pumpkin"}


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
    lo_mhz: float = 0.0                      # transverter local oscillator (0 = none)
    extra: dict = field(default_factory=dict)

    @property
    def rig_hz(self):
        """Frequency to put on the rig's dial (IF frequency when a transverter is used)."""
        return (self.freq_mhz - self.lo_mhz) * 1e6

    @property
    def label(self):
        m = self.submode if self.mode in ("ur", "pumpkin", "cucumber") else self.mode.upper()
        return f"{self.band}_{m}_{self.freq_mhz:.3f}"


def load_config(path):
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    slots = []
    for band in cfg["band"]:
        if not band.get("active", True):
            continue
        for s in band["slot"]:
            known = {k: s[k] for k in ("mode", "freq_mhz", "enabled", "submode",
                                       "msg_type", "msg_value", "note") if k in s}
            known["mode"] = LEGACY.get(known.get("mode"), known.get("mode"))
            if str(known.get("submode", "")).startswith("URC-"):          # names before v0.6
                known["submode"] = "PUMPKIN-" + known["submode"].split("-")[1]
            slots.append(Slot(band=band["name"], lo_mhz=float(band.get("transverter_lo_mhz", 0.0)), **known))
    st = cfg["station"]
    if st.get("callsign", "N0CALL").upper() in ("N0CALL", "NOCALL", ""):
        raise SystemExit("Set your own callsign in [station] callsign before running.")
    return cfg, slots


def slot_duration(slot, cfg=None):
    if slot.mode == "ur":
        return urmode.NSYM * urmode.SUBMODES[slot.submode]
    if slot.mode == "pumpkin":
        return (pumpkin.NSYM + 1) * pumpkin.SUBMODES[slot.submode]
    if slot.mode == "cucumber":
        return (cucumber.NSYM + 1) * cucumber.SUBMODES[slot.submode]
    if slot.mode == "aprs":
        return 1.2                          # typical; actual length comes from the audio
    return DURATION[slot.mode]


def align(t, slot):
    """Earliest legal start time >= t for this slot."""
    if slot.mode == "aprs":
        return t
    if slot.mode == "ft8":
        period, offset = 15, 0.5
    elif slot.mode == "ft4":
        period, offset = 7.5, 0.5
    elif slot.mode == "wspr":
        period, offset = 120, 1.0
    elif slot.mode == "pumpkin":
        period, offset = pumpkin.PERIODS[slot.submode], 1.0
    elif slot.mode == "cucumber":
        period, offset = cucumber.PERIODS[slot.submode], 1.0
    else:
        period, offset = urmode.PERIODS[slot.submode], 1.0
    start = math.ceil((t - offset) / period) * period + offset
    return start


def rig_mode(s, rigmodes):
    """Radio mode for a slot: APRS is FM on VHF/UHF but USB (300 baud) on HF."""
    if s.mode == "aprs" and s.freq_mhz < 30.0:
        return "USB"
    return rigmodes[s.mode]


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
        # Listening in the gaps between transmissions (set by the GUI / CLI):
        self.listen_in_gaps = False
        self.on_event = None                 # decoder events for the window
        self.reporter = None                 # PSK Reporter uploader
        self.decoding = False
        self._gap_warned = set()
        self.blocked = {}                    # band -> SWR that tripped; not used again this session

    def audio_for(self, s):
        st = self.st
        off = float(st.get("audio_offset_hz", 1500))
        if s.mode == "aprs":
            info = aprs.position_info(st["lat"], st["lon"], st.get("aprs_symbol_table", "/"),
                                      st.get("aprs_symbol", "-"), st.get("aprs_comment", ""))
            src = f"{st['callsign']}-{st.get('aprs_ssid', 0)}" if st.get("aprs_ssid") else st["callsign"]
            path = tuple(p for p in st.get("aprs_path", "WIDE1-1,WIDE2-1").split(",") if p)
            if abs(s.freq_mhz - 145.825) < 0.001:
                path = ("ARISS",)            # ISS / satellite digipeaters answer only to ARISS
            hf = s.freq_mhz < 30.0           # HF APRS: 300 baud on USB, no digipeater path
            if hf:
                path = tuple(p for p in st.get("aprs_hf_path", "").split(",") if p)
            return aprs.packet_audio(src, info, path=path, hf=hf), aprs.FS
        if s.mode == "ft8":
            return wsjt.ft8_audio(f"CQ {st['callsign']} {st['grid']}", off), wsjt.FS
        if s.mode == "ft4":
            return wsjt.ft4_audio(f"CQ {st['callsign']} {st['grid']}", off), wsjt.FS
        if s.mode == "wspr":
            return wsjt.wspr_audio(st["callsign"], st["grid"], int(st["wspr_power_dbm"]), off), wsjt.FS
        if s.mode == "cucumber":
            sym = cucumber.message_to_symbols(st["callsign"], st["grid"], s.msg_type, s.msg_value)
            return cucumber.modulate(sym, s.submode), cucumber.FS
        if s.mode == "pumpkin":
            sym = pumpkin.message_to_symbols(st["callsign"], st["grid"], s.msg_type, s.msg_value)
            return pumpkin.modulate(sym, s.submode, f0=off), pumpkin.FS
        tones = urmode.message_to_tones(st["callsign"], st["grid"], s.msg_type, s.msg_value)
        return urmode.modulate(tones, s.submode, f0=off), urmode.FS

    def run(self, cycles=None, until=None):
        """Transmit cycle after cycle. With `until` (clock.now()), stop before a slot that would run past it."""
        if not bands_of(self.slots):
            log.warning("no band and mode is ticked for transmitting")
            if until is not None:
                self._sleep_until(until)
            return
        if ntp_ok() is False:
            log.warning("System clock is NOT NTP-synchronised: FT8/WSPR/UR will not decode.")
        cs = self.cfg.get("carrier_sense", {})
        rigmodes = {**RIG_MODE_DEFAULT, **self.cfg.get("rig_modes", {})}
        done = 0
        while cycles is None or done < cycles:
            for band, band_slots in bands_of(self.slots):
                for i, s in enumerate(band_slots):
                    if self.stop.is_set():
                        log.info("stopped")
                        return
                    if band in self.blocked:
                        break
                    if until is not None and clock.now() + 25 > until:
                        return
                    self._one(s, rigmodes, cs, band)
                    gap_end = clock.now() + gap_after(self.cfg, band_slots, i)
                    self._gap(s, gap_end if until is None else min(gap_end, until))
            if self.blocked and all(b in self.blocked for b, _ in bands_of(self.slots)):
                log.error("every band has been stopped for high SWR - not transmitting any more")
                self._emit({"type": "swr_stop"})
                return
            done += 1

    def _emit(self, ev):
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:                # noqa: BLE001
                pass

    def _one(self, s, rigmodes, cs, band=None):
        try:
            audio, fs = self.audio_for(s)
        except Exception as e:               # noqa: BLE001
            log.error("skip %s: %s", s.label, e)
            return
        begin = align(clock.now() + 4, s)    # 4 s to tune the rig
        self._sleep_until(begin - 3)
        if self.stop.is_set():
            return
        mode = rig_mode(s, rigmodes)
        self.radio.tune(s.rig_hz, mode)
        if s.mode == "aprs" and cs.get("enabled", True):
            if not self._clear(cs):
                log.warning("%s: channel busy, skipped", s.label)
                return
        else:
            self._sleep_until(begin)
        log.info("TX %s at %s UTC", s.label,
                 dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S.%f")[:-3])
        from .radio import SWRError
        self._emit({"type": "tx_start", "label": s.label, "freq_mhz": s.freq_mhz, "mode": s.mode,
                    "seconds": len(audio) / fs})
        try:
            self.radio.transmit(s.rig_hz, mode, audio, fs, s.label)
        except SWRError as e:
            key = band if band is not None else s.freq_mhz
            self.blocked[key] = e.swr
            log.error("HIGH SWR %.1f (limit %.1f) on %.4f MHz - PTT dropped; no more transmitting on this band "
                      "until you check the antenna and press ON AIR again", e.swr, e.limit, s.freq_mhz)
            self._emit({"type": "swr_trip", "swr": e.swr, "limit": e.limit, "freq_mhz": s.freq_mhz,
                        "band": str(key), "label": s.label})
        finally:
            swr = getattr(self.radio, "last_swr", None)
            self._emit({"type": "tx_end", "label": s.label, "swr": swr})

    def _gap(self, s, until):
        """Wait until `until`. If enabled, decode on the slot just sent (same frequency and mode) meanwhile,
        like WSJT-X listening between its own transmissions."""
        if self.listen_in_gaps and not self.stop.is_set() and type(self.radio).__name__ != "DryRunRadio":
            import copy
            from . import monitor
            cfg = copy.deepcopy(self.cfg)
            sub = s.submode if s.mode in ("pumpkin", "cucumber", "ur") else s.mode.upper()
            cfg["receive"] = {**cfg.get("receive", {}), "mode": s.mode, "submode": sub,
                              "dial_mhz": s.freq_mhz, "source": "audio"}
            try:
                lis = monitor.Listener(cfg, self.reporter, on_event=self.on_event)
                lis.stop = self.stop
                self.decoding = True
                log.info("listening on %.4f MHz (%s) until the next transmission", s.freq_mhz, sub)
                lis.run(until=until - 4)              # 4 s to retune for the next transmission
            except Exception as e:                    # noqa: BLE001 - e.g. WSJT-X missing for FT8/WSPR
                if s.mode not in self._gap_warned:
                    self._gap_warned.add(s.mode)
                    log.warning("not decoding %s between transmissions: %s", s.mode.upper(), e)
            finally:
                self.decoding = False
                if self.on_event:
                    self.on_event({"type": "gap_end"})
        self._sleep_until(until)

    def _clear(self, cs):
        for _ in range(int(cs.get("retries", 3)) + 1):
            if not self.radio.channel_busy(cs.get("listen_s", 2.0), cs.get("threshold_db", -40)):
                return True
            time.sleep(random.uniform(3, 10))
        return False

    def _sleep_until(self, t):
        while not self.stop.is_set():
            r = t - clock.now()
            if r <= 0:
                return
            self.stop.wait(min(r, 0.5) if r > 0.05 else r)


class Session:
    """ON AIR. Without a timetable: the Runner transmits all the time, decoding in the gaps. With one
    (timetable.py): transmit windows send on their own N-minute grid (09:03, 09:06 ...) cycling through the
    ticked bands and modes and decode in between; listen windows only decode; pause windows wait.
    One stop event, so Stop ends whatever is running. All times come from the NTP-corrected clock."""

    def __init__(self, cfg, slots, radio):
        from . import timetable
        self.cfg, self.radio, self.slots = cfg, radio, slots
        self.tt = timetable.settings(cfg)
        self.runner = Runner(cfg, slots, radio)
        self.stop = self.runner.stop
        self.on_event = None
        self.reporter = None
        self.listen_in_gaps = True
        self.listener_factory = None              # tests replace the decoder
        self._k = 0                               # rotation through the ticked slots

    def _emit(self, ev):
        if self.on_event:
            try:
                self.on_event(ev)
            except Exception:                     # noqa: BLE001
                pass

    def run(self, max_windows=None):
        from . import timetable
        r = self.runner
        r.on_event, r.reporter, r.listen_in_gaps = self.on_event, self.reporter, self.listen_in_gaps
        if clock.offset() is None:
            clock.sync()
        log.info("%s", clock.status())
        if not self.tt["enabled"] or not self.tt["windows"]:
            r.run()
            return
        log.info("%s", timetable.describe(self.tt))
        n = 0
        while not self.stop.is_set() and (max_windows is None or n < max_windows):
            w, action, end = timetable.at(self.tt, clock.now())
            self._emit({"type": "phase", "phase": {"transmit": "tx", "listen": "listen"}.get(action, "off"),
                        "until": end, "window": w.text() if w else "outside the timetable"})
            if action == "transmit" and bands_of(self.slots):
                self._transmit(w, end)
            elif action in ("listen", "transmit"):
                if action == "transmit":
                    log.warning("transmit window but no band and mode is ticked - listening instead")
                self._listen(end)
            else:
                log.info("paused until %s", time.strftime("%H:%M", time.localtime(end)))
            r._sleep_until(end)
            n += 1

    def _next_slot(self):
        flat = [(b, s) for b, ss in bands_of(self.slots) for s in ss if b not in self.runner.blocked]
        if not flat:
            return None, None
        b, s = flat[self._k % len(flat)]
        self._k += 1
        return b, s

    def _transmit(self, w, end):
        from . import timetable
        r = self.runner
        cs = self.cfg.get("carrier_sense", {})
        rigmodes = {**RIG_MODE_DEFAULT, **self.cfg.get("rig_modes", {})}
        tick_list = timetable.ticks(w, clock.now() + 6, end, self.tt)
        log.info("transmit window %s: %d transmissions, first at %s", w.text(), len(tick_list),
                 time.strftime("%H:%M:%S", time.localtime(tick_list[0])) if tick_list else "-")
        if tick_list and tick_list[0] - clock.now() > 40:
            self._emit({"type": "next_tx", "at": tick_list[0]})
            self._listen(tick_list[0] - 6)         # decode until the first transmission
        for i, tick in enumerate(tick_list):
            if self.stop.is_set():
                return
            band, s = self._next_slot()
            if s is None:
                log.error("every band has been stopped for high SWR - listening for the rest of this window")
                self._emit({"type": "swr_stop"})
                self._listen(end)
                return
            r._sleep_until(tick - 5)
            if self.stop.is_set():
                return
            r._one(s, rigmodes, cs, band)          # aligns to the tick (FT8 / FT4 slot, WSPR even minute)
            nxt = tick_list[i + 1] if i + 1 < len(tick_list) else end
            self._emit({"type": "next_tx", "at": nxt if i + 1 < len(tick_list) else None})
            r._gap(s, nxt - 5)                     # decode on this frequency until just before the next one

    def _listen(self, end):
        from . import monitor
        if end - clock.now() < 10:
            return
        rx = self.cfg.get("receive", {})
        try:
            if hasattr(self.radio, "tune"):
                self.radio.tune(float(rx.get("dial_mhz", 144.49)) * 1e6, monitor.receive_rig_mode(rx))
        except Exception as e:                    # noqa: BLE001
            log.warning("could not tune for listening (%s); using the radio's current frequency", e)
        try:
            make = self.listener_factory or (lambda: monitor.Listener(self.cfg, self.reporter,
                                                                      on_event=self.on_event))
            lis = make()
            lis.stop = self.stop
            self._emit({"type": "phase", "phase": "listen", "until": end, "window": "listening"})
            lis.run(until=end)
        except Exception as e:                    # noqa: BLE001
            log.warning("not decoding now: %s", e)
        finally:
            self._emit({"type": "gap_end"})
