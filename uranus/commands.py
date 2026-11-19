"""Plain-English commands: type what you want and Uranus sets it up.

Runs entirely on this computer (no AI service, no internet): a small set of patterns for the things people ask
a station to do. Examples:
  listen on 2 m tonight and wake me for an opening
  beacon wspr every 10 minutes overnight
  weather fax from New Orleans
  scan 20 m and 40 m for ft8
  what is this?            which band is best?          ping K1ABC
  hurricane watch           check the station           find the noise
  speak on                  large text                  stop
`parse()` returns a Plan: a list of actions for the GUI to carry out and a sentence saying what it will do.
"""
import re
from dataclasses import dataclass, field

from . import freqplan, profiles

MODES = {"ft8": "FT8", "ft4": "FT4", "q65": "Q65", "jt65": "JT65", "jt9": "JT9", "fst4w": "FST4W", "fst4": "FST4",
         "wspr": "WSPR", "aprs": "APRS", "pumpkin": "PUMPKIN-60", "cucumber": "CUCUMBER-60", "ur": "UR-60",
         "auto": "AUTO", "everything": "AUTO"}
FAX = {"new orleans": "NMG", "nmg": "NMG", "boston": "NMF", "nmf": "NMF", "point reyes": "NMC", "nmc": "NMC",
       "kodiak": "NOJ", "honolulu": "KVM70", "hawaii": "KVM70", "halifax": "CFH", "hamburg": "DDH3",
       "tokyo": "JMH", "australia": "VMW", "wiluna": "VMW"}
TIMES = {"tonight": "18:00-06:00", "overnight": "22:00-06:00", "all night": "22:00-06:00",
         "all day": "00:00-23:59", "today": "06:00-18:00", "this morning": "06:00-12:00",
         "this afternoon": "12:00-18:00", "this evening": "17:00-22:00"}


@dataclass
class Plan:
    actions: list = field(default_factory=list)     # [{"do": ..., ...}]
    said: list = field(default_factory=list)

    @property
    def text(self):
        return " ".join(self.said) if self.said else ("Sorry, I didn't understand that. Try: 'listen on 2 m "
                                                      "tonight', 'weather fax from New Orleans', 'scan 20 m for "
                                                      "ft8', 'which band is best?', 'hurricane watch'.")


def _bands(t):
    out = []
    for num, unit in re.findall(r"\b(\d+(?:\.\d+)?)\s*(m|metres?|meters?|cm)\b", t):
        name = f"{num}{'cm' if unit == 'cm' else 'm'}"
        if name in freqplan.BAND_EDGES:
            out.append(name)
    return out


def _mhz(t):
    m = re.search(r"\b(\d{1,3}\.\d{2,4})\s*(?:mhz)?\b", t)
    return float(m.group(1)) if m else None


def _mode(t):
    for w, sub in MODES.items():
        if re.search(rf"\b{w}\b", t):
            return w, sub
    return None, None


def _hh(s, pm=None):
    h, _, m = s.partition(":")
    h, m = int(h), int(m or 0)
    if pm == "pm" and h < 12:
        h += 12
    if pm == "am" and h == 12:
        h = 0
    return f"{h % 24:02d}:{m:02d}"


def _window(t):
    m = re.search(r"\b(?:from\s+)?(\d{1,2}(?::\d{2})?)\s*(am|pm)?\s*(?:to|until|-|till)\s*(\d{1,2}(?::\d{2})?)\s*(am|pm)?",
                  t)
    if m and ("from" in t or ":" in m.group(0) or m.group(2) or m.group(4)):
        return f"{_hh(m.group(1), m.group(2) or m.group(4))}-{_hh(m.group(3), m.group(4))}"
    for w, span in TIMES.items():
        if w in t:
            return span
    return None


def parse(text, dial_mhz=None):
    t = " " + " ".join(text.lower().replace("?", " ").replace(",", " ").split()) + " "
    p = Plan()
    if re.search(r"\b(stop|halt|cancel)\b", t) and len(t.split()) <= 3:
        p.actions.append({"do": "stop"})
        p.said.append("Stopping.")
        return p
    mission = None
    for m in profiles.MISSIONS:
        if m.name.lower() in t or f" mission {m.key} " in t or (m.key in t and "mission" in t):
            mission = m
    if mission:
        p.actions.append({"do": "mission", "key": mission.key})
        p.said.append(f"Setting up the {mission.name} mission.")
    if re.search(r"what is (this|that)|what am i hearing|identify|signal id|what'?s this", t):
        p.actions.append({"do": "signal_id", "dial_mhz": _mhz(t) or dial_mhz})
        p.said.append("Listening for 15 seconds to identify the signal.")
    if re.search(r"best band|which band|what band|band (is )?open|where should i", t):
        p.actions.append({"do": "best"})
        p.said.append("Working out the best band now.")
    if re.search(r"\b(health|check (the )?station|self.?test|is everything ok)\b", t):
        p.actions.append({"do": "health"})
        p.said.append("Checking the station.")
    if re.search(r"\b(noise|interference|hum|buzz|qrm)\b", t) and re.search(r"find|hunt|fix|doctor|where|why", t):
        p.actions.append({"do": "doctor"})
        p.said.append("Starting the interference doctor.")
    if re.search(r"\b(fax|wefax|weather chart|weather map|radiofax)\b", t):
        call = next((c for w, c in FAX.items() if w in t), None)
        p.actions.append({"do": "wefax", "call": call, "autopilot": True})
        p.said.append(f"Opening weather fax{' for ' + call if call else ''} with the autopilot on.")
    mping = re.search(r"\bping\s+([a-z0-9/]{3,10})\b", t)
    if mping:
        p.actions.append({"do": "ping", "call": mping.group(1).upper()})
        p.said.append(f"Pinging {mping.group(1).upper()} in Chat.")
    if re.search(r"\b(map)\b", t) and not p.actions:
        p.actions.append({"do": "map"})
        p.said.append("Opening the station map.")
    bands = _bands(t)
    mode, sub = _mode(t)
    if re.search(r"\bscan", t):
        modes = [w for w in MODES if re.search(rf"\b{w}\b", t) and w not in ("auto", "everything")] or ["ft8", "ft4"]
        p.actions.append({"do": "scan", "bands": bands or ["20m"], "modes": modes})
        p.said.append(f"Scanning {', '.join(freqplan.BAND_NAMES[b] for b in bands or ['20m'])} for "
                      f"{', '.join(m.upper() for m in modes)}.")
    win = _window(t)
    if re.search(r"\b(listen|decode|monitor|watch)\b", t) and not mission and "scan" not in t:
        dial = _mhz(t)
        if dial is None and bands:
            m0 = mode or "ft8"
            opts = freqplan.options(bands[0], {"auto": "ft8", "everything": "ft8"}.get(m0, m0)) or \
                freqplan.options(bands[0], "ft8")
            dial = opts[0].mhz if opts else None
        act = {"do": "listen", "submode": sub or "AUTO", "dial_mhz": dial, "window": win}
        p.actions.append(act)
        where = f" on {freqplan.fmt(dial)} MHz" if dial else ""
        p.said.append(f"Listening for {sub or 'AUTO'}{where}" + (f", {win}" if win else "") + ".")
    mt = re.search(r"\b(beacon|transmit|send|tx)\b", t)
    if mt and not mission:
        every = re.search(r"every\s+(\d+)\s*(?:min|minutes?)", t)
        n = int(every.group(1)) if every else 10
        act = {"do": "beacon", "every": n, "window": win or "00:00-23:59", "mode": mode}
        p.actions.append(act)
        p.said.append(f"Transmitting every {n} minutes, {act['window']}" +
                      (f" ({mode.upper()} must be ticked in Bands and modes)" if mode else "") + ".")
    if re.search(r"wake me|alert me|tell me when|let me know", t):
        p.actions.append({"do": "alert", "what": "opening", "band": bands[0] if bands else None})
        p.said.append("I'll sound an alert and speak when a new station is heard.")
    if re.search(r"\b(speak|talk|voice)\b", t) and re.search(r"\b(on|off|stop|start|enable|disable)\b", t):
        on = not re.search(r"\b(off|stop|disable|quiet)\b", t)
        p.actions.append({"do": "access", "speak": on})
        p.said.append(f"Spoken announcements {'on' if on else 'off'}.")
    if re.search(r"(large|big|bigger) (text|font|type)", t):
        p.actions.append({"do": "access", "large_text": True})
        p.said.append("Large text on (takes effect when Uranus restarts).")
    return p
