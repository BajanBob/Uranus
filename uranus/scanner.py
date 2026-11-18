"""Scanner: step the radio (by CAT) through known and user frequencies, stop where there is activity.

On each channel Uranus listens to one 15-second AUTO slot (FT8 is decoded, everything else identified by its
signature). If anything is heard it stays on that channel, decoding in the channel's own mode, for up to
`dwell_s` (3 minutes) or until two slots in a row are quiet, then moves on. While it is stopped on a channel
you can press Continue (move on now) or Ignore (move on and skip this channel for the rest of the scan).
"""
import copy
import logging
import threading
import time

from . import freqplan

log = logging.getLogger("uranus.scanner")

DWELL_S = 180
FM = ("aprs", "cucumber")
SLOW = {"wspr": 120, "fst4w": 120, "q65": 60, "jt65": 60, "jt9": 60, "fst4": 60}
WSJT = ("ft8", "ft4", "q65", "jt65", "jt9", "fst4", "fst4w", "wspr")


class _Either:
    """Looks like a threading.Event to the listener: set when either the scan or the channel is stopped."""

    def __init__(self, *evs):
        self.evs = evs

    def is_set(self):
        return any(e.is_set() for e in self.evs)

    def set(self):
        self.evs[-1].set()

    def wait(self, timeout=None):
        end = None if timeout is None else time.time() + timeout
        while not self.is_set():
            if end is not None and time.time() >= end:
                return False
            time.sleep(0.05 if end is None else max(0.0, min(0.1, end - time.time())))
        return True


class Channel:
    def __init__(self, band, mode, mhz, note=""):
        self.band, self.mode, self.mhz, self.note = band, mode, float(mhz), note

    @property
    def key(self):
        return (self.mode, round(self.mhz, 6))

    @property
    def rig_mode(self):
        return "FM" if self.mode in FM and self.mhz > 30 else "USB"

    def label(self):
        return f"{freqplan.fmt(self.mhz)} MHz {self.mode.upper()} ({freqplan.BAND_NAMES.get(self.band, self.band)})"


def channels(bands, modes, plan=None):
    """Every band-plan frequency on the chosen bands and modes, once each, low to high."""
    seen, out = set(), []
    for f in sorted(plan if plan is not None else freqplan.PLAN, key=lambda f: f.mhz):
        if f.band in bands and f.mode in modes and (f.mode, round(f.mhz, 6)) not in seen:
            seen.add((f.mode, round(f.mhz, 6)))
            out.append(Channel(f.band, f.mode, f.mhz, f.note))
    return out


def submode_of(mode):
    return {"pumpkin": "PUMPKIN-60", "cucumber": "CUCUMBER-60", "ur": "UR-60"}.get(mode, mode.upper())


class Scanner:
    """Runs in its own thread. on_event gets {"type": "scan", ...} for the GUI and passes listener events on."""

    def __init__(self, cfg, chans, reporter=None, on_event=None, dwell_s=DWELL_S, tune=None, listener=None):
        self.cfg, self.chans = cfg, list(chans)
        self.reporter = reporter
        self.on_event = on_event or (lambda e: None)
        self.dwell_s = dwell_s
        self.ignored = set()
        self.stop = threading.Event()
        self._skip = threading.Event()
        self._cur = None                       # stop event of the listener now running
        self.current = None
        self.submode = "SCAN"                  # the GUI shows the decoder panel while this runs
        if tune is None:
            from . import tuning
            tune = lambda ch: tuning.tune(self.cfg, ch.mhz, ch.rig_mode)   # noqa: E731
        self.tune = tune
        if listener is None:
            from .monitor import Listener
            listener = Listener
        self.Listener = listener

    # -- controls (any thread)
    def cont(self):
        """Leave the current channel now."""
        self._skip.set()
        if self._cur:
            self._cur.set()

    def ignore(self):
        """Leave the current channel and do not come back to it this scan."""
        if self.current is not None:
            self.ignored.add(self.current.key)
            self._emit("ignored", self.current)
        self.cont()

    def halt(self):
        self.stop.set()
        self.cont()

    # -- work
    def _emit(self, state, ch=None, **kw):
        self.on_event({"type": "scan", "state": state, "chan": ch.label() if ch else "",
                       "mode": ch.mode if ch else "", "mhz": ch.mhz if ch else 0, **kw})

    def _listen(self, ch, mode, slots):
        """Listen in `mode` on the channel for `slots` slots. Returns (decodes, identified signals)."""
        cfg = copy.deepcopy(self.cfg)
        cfg["receive"] = {**cfg.get("receive", {}), "mode": mode, "submode": submode_of(mode),
                          "dial_mhz": ch.mhz}
        got = {"decodes": 0, "signals": 0}

        def ev(e):
            if e["type"] == "result":
                got["decodes"] += e.get("count", 0)
            elif e["type"] == "identified":
                got["signals"] += sum(1 for i in e["items"] if i["mode"] != "Unknown" and i["confidence"] >= 0.5)
            self.on_event(e)
        self._cur = threading.Event()
        lis = self.Listener(cfg, self.reporter, on_event=ev)
        lis.stop = _Either(self.stop, self._cur)
        lis.follow = None
        try:
            lis.run(slots=slots)
        except Exception as e:                  # noqa: BLE001 - a bad channel must not end the scan
            log.warning("scanner: %s: %s", ch.label(), e)
        return got["decodes"], got["signals"]

    def run(self):
        n_pass = 0
        while not self.stop.is_set():
            todo = [c for c in self.chans if c.key not in self.ignored]
            if not todo:
                self._emit("done", reason="every channel is ignored")
                return
            n_pass += 1
            for ch in todo:
                if self.stop.is_set() or ch.key in self.ignored:
                    break
                self.current = ch
                self._skip.clear()
                try:
                    msg = self.tune(ch)
                except Exception as e:          # noqa: BLE001
                    msg = f"could not tune ({e})"
                self._emit("probe", ch, note=msg, scan_pass=n_pass)
                # FM channels (APRS, Cucumber) are probed in their own mode; everything else with AUTO
                probe_mode = ch.mode if ch.mode in FM else "auto"
                dec, sig = self._listen(ch, probe_mode, 1)
                if self.stop.is_set():
                    break
                if self._skip.is_set() or not (dec or sig):
                    self._emit("quiet", ch)
                    continue
                self._dwell(ch)
        self._emit("stopped")

    def _dwell(self, ch):
        until = time.time() + self.dwell_s
        quiet = 0
        self._emit("dwell", ch, until=until)
        mode = ch.mode if ch.mode in WSJT or ch.mode in FM else "auto"
        while not self.stop.is_set() and not self._skip.is_set() and time.time() < until:
            dec, sig = self._listen(ch, mode, 1)
            quiet = 0 if (dec or sig) else quiet + 1
            if quiet >= 2:
                self._emit("ended", ch, reason="transmissions stopped")
                return
        self._emit("ended", ch, reason="continue pressed" if self._skip.is_set() else "time up")
