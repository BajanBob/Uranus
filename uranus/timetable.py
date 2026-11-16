"""Timetable: what ON AIR does at each time of day.

[timetable] in uranus.toml:
  enabled = true
  clock   = "local" or "utc"
  outside = "listen" or "pause"        what to do at times no window covers
  windows = ['01:00-06:00 transmit 3', '07:00-09:00 listen', '09:03-22:00 transmit 3', '22:00-23:59 listen']

A transmit window sends on its own grid: at the start time and every N minutes after it (09:03, 09:06, 09:09
...), cycling through the bands and modes ticked in Bands and modes, and decodes on that frequency in
between. A listen window only listens and decodes (Decode and Dial boxes). Times use the NTP-corrected clock.
"""

import re
import time

ACTIONS = ("transmit", "listen", "pause")
INTERVALS = [2, 3, 4, 5, 6, 10, 15, 20, 30, 60]   # minutes between transmissions
EXAMPLE = ["01:00-06:00 transmit 3", "07:00-09:00 listen", "09:03-22:00 transmit 3", "22:00-23:59 listen"]

_RX = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s+(transmit|listen|pause)(?:\s+(\d+))?\s*$", re.I)


class Window:
    def __init__(self, start_min, end_min, action, every_min=3):
        self.start, self.end, self.action, self.every = start_min, end_min, action, int(every_min or 3)

    @property
    def length(self):
        return (self.end - self.start) % 1440 or 1440

    def covers(self, minute):
        """minute of the day (float) inside [start, end)"""
        return (minute - self.start) % 1440 < self.length

    def text(self):
        s = f"{hhmm(self.start)}-{hhmm(self.end)} {self.action}"
        return s + f" {self.every}" if self.action == "transmit" else s

    def describe(self):
        what = {"transmit": f"transmit every {self.every} min, decoding in between",
                "listen": "listen and decode", "pause": "pause"}[self.action]
        return f"{hhmm(self.start)}-{hhmm(self.end)}  {what}"

    def __repr__(self):
        return f"Window({self.text()!r})"


def hhmm(m):
    m = int(round(m)) % 1440 if m != 1440 else 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_time(text):
    h, m = (int(x) for x in str(text).strip().split(":"))
    if not (0 <= h <= 24 and 0 <= m < 60) or (h == 24 and m):
        raise ValueError(f"not a time: {text}")
    return h * 60 + m


def parse(line):
    m = _RX.match(str(line))
    if not m:
        raise ValueError(f"cannot read timetable line '{line}' (use e.g. '09:03-22:00 transmit 3')")
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    if a > 1440 or b > 1440 or int(m[2]) > 59 or int(m[4]) > 59:
        raise ValueError(f"bad time in '{line}'")
    if a == b:
        raise ValueError(f"'{line}' starts and ends at the same time")
    every = int(m[6] or 3)
    if not 1 <= every <= 240:
        raise ValueError(f"'{line}': transmit every 1 to 240 minutes")
    return Window(a % 1440, b % 1440 if b != 1440 else 0, m[5].lower(), every)


def settings(cfg):
    t = dict(cfg.get("timetable", {}))
    t["enabled"] = bool(t.get("enabled", False))
    t["clock"] = "utc" if str(t.get("clock", "local")).lower() == "utc" else "local"
    t["outside"] = "pause" if str(t.get("outside", "listen")).lower() == "pause" else "listen"
    t["windows"] = [parse(x) for x in t.get("windows", [])]
    return t


def overlaps(windows):
    """Pairs of window texts that overlap (the first in the list wins at those times)."""
    out = []
    for i, a in enumerate(windows):
        for b in windows[i + 1:]:
            if a.covers(b.start) or b.covers(a.start):
                out.append((a.text(), b.text()))
    return out


def _minute_of_day(t, clock):
    st = time.gmtime(t) if clock == "utc" else time.localtime(t)
    return st.tm_hour * 60 + st.tm_min + (st.tm_sec + t % 1) / 60


def at(tt, t):
    """(window or None, action, end_time) at time t: what to do now and until when (seconds)."""
    m = _minute_of_day(t, tt["clock"])
    for w in tt["windows"]:
        if w.covers(m):
            return w, w.action, t + (w.length - (m - w.start) % 1440) * 60
    # outside every window: until the next window starts
    nxt = min(((w.start - m) % 1440 for w in tt["windows"]), default=1440) or 1440
    return None, tt["outside"], t + nxt * 60


def ticks(w, t, end, tt):
    """Transmit times (seconds) of window w from time t up to (not including) end."""
    m = _minute_of_day(t, tt["clock"])
    into = (m - w.start) % 1440                       # minutes since the window started
    k = int(-(-into // w.every))                      # next tick index (ceil)
    first = t + (k * w.every - into) * 60
    out, x = [], first
    while x < end - 1:
        out.append(round(x))                          # whole seconds: ticks fall on :00
        x += w.every * 60
    return out


def describe(tt):
    if not tt["enabled"] or not tt["windows"]:
        return "Transmit all the time, decoding between transmissions"
    clk = "UTC" if tt["clock"] == "utc" else "local time"
    rest = "listen and decode" if tt["outside"] == "listen" else "pause"
    return f"Timetable ({clk}): " + "; ".join(w.describe() for w in tt["windows"]) + f"; other times {rest}"
