"""Pumpkin ping: ask another Uranus station whether two-way contact is possible right now.

It runs over Chat (Pumpkin on SSB or Cucumber on FM), so both stations need the Chat window open on the same
frequency and mode, one sending in even slots and the other in odd ones. The exchange is like a short FT8 QSO,
one 11-character chat frame per step, each after an ID frame (callsign and grid):

    A -> B   PING B          "can you hear me?"
    B -> A   R-18A           automatic reply: "I hear you at -18 dB"
    A -> B   RR-21B          automatic: "and I hear you at -21 dB" -> two-way contact for A
                             B gets the RR -> two-way contact for B as well

Each side then shows a Pumpkin Report: signal (SNR) each way, the date and time (UTC), the distance between the
two grids, the frequency and mode. Contacts are kept in out/contacts.jsonl; the station map draws a smashed
pumpkin for every station you have had a two-way contact with.
"""
import json
import os
import re
import time

from . import geo, propagation, spots

CONTACTS = os.path.join(os.path.dirname(spots.DEFAULT_PATH), "contacts.jsonl")
PATHS = os.path.join(os.path.dirname(spots.DEFAULT_PATH), "paths.jsonl")   # overheard ping paths (network map)
_CALL = r"[A-Z0-9/]{3,7}"
_PING = re.compile(rf"^PING ({_CALL})$")
_R = re.compile(rf"^(RR?)([+-]\d\d)({_CALL})$")
REPLY_WITHIN_S = 15 * 60                # a report only counts for a ping we sent in the last 15 minutes


def snr_txt(snr):
    v = max(-99, min(49, int(round(snr if snr is not None else -99))))
    return f"{v:+03d}"


def ping_text(to_call):
    return f"PING {to_call.upper()}"


def report_text(snr, to_call, final=False):
    return ("RR" if final else "R") + snr_txt(snr) + to_call.upper()


def parse(text):
    """('ping', to, None) / ('report', to, snr) / ('final', to, snr) / None for ordinary chat."""
    t = " ".join(text.upper().split())
    m = _PING.match(t)
    if m:
        return ("ping", m.group(1), None)
    m = _R.match(t.replace(" ", ""))
    if m:
        return ("final" if m.group(1) == "RR" else "report", m.group(3), int(m.group(2)))
    return None


def km_between(grid_a, grid_b):
    try:
        return round(geo.distance_km(geo.grid_to_latlon(grid_a), geo.grid_to_latlon(grid_b)))
    except (ValueError, KeyError, IndexError, TypeError):
        return None


def describe(c):
    """The Pumpkin Report as a few lines of text."""
    when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(c["time"]))
    way = "TWO-WAY CONTACT" if c.get("two_way") else "one way so far"
    they = f"{c['they_heard_me']:+d} dB" if c.get("they_heard_me") is not None else "not yet"
    me = f"{c['i_heard_them']:+.0f} dB" if c.get("i_heard_them") is not None else "-"
    km = f"{c['km']:,} km" if c.get("km") is not None else "distance unknown"
    return (f"PUMPKIN REPORT  {c['call']} ({c.get('grid') or '?'})  {way}\n"
            f"  They heard you: {they}   You heard them: {me}\n"
            f"  {when} · {km} · {c.get('freq_hz', 0) / 1e6:.4f} MHz {c.get('submode', '')}")


def load(path=CONTACTS):
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return out


def network(path=PATHS, since_s=7 * 86400, now=None):
    """Latest overheard path for each pair of stations, both grids known: [{a, a_grid, b, b_grid, snr, time}]"""
    now = now or time.time()
    best = {}
    for p in load(path):
        if now - p.get("time", 0) > since_s or not (p.get("heard_grid") and p.get("by_grid")):
            continue
        k = tuple(sorted((p["heard"], p["by"])))
        if p["time"] >= best.get(k, {}).get("time", 0):
            best[k] = p
    return list(best.values())


def two_way(path=CONTACTS):
    """call -> latest two-way contact (for the smashed pumpkins on the map)."""
    best = {}
    for c in load(path):
        if c.get("two_way") and c.get("time", 0) >= best.get(c["call"], {}).get("time", 0):
            best[c["call"]] = c
    return best


class PingAgent:
    """Watches chat events, answers pings automatically and writes Pumpkin Reports.
    `send(text)` queues a chat message with an ID frame in front of it."""

    def __init__(self, call, grid, send, freq_hz=0.0, submode="", on_event=None, path=CONTACTS, auto_reply=True):
        self.call, self.grid = call.upper().split("-")[0], grid
        self.send = send
        self.freq_hz, self.submode = freq_hz, submode
        self.on_event = on_event or (lambda e: None)
        self.path = path
        self.paths_path = os.path.join(os.path.dirname(path) or ".", "paths.jsonl")
        self.auto_reply = auto_reply
        self.grids = {}                         # call -> grid from ID frames
        self.pinged = {}                        # call -> time we pinged them
        self.heard = {}                         # call -> SNR we heard their ping / report at
        self.done = {}                          # call -> time of the last two-way contact (no double logging)

    def ping(self, to_call):
        to = to_call.upper().strip().split("-")[0]
        self.pinged[to] = time.time()
        self.send(ping_text(to))
        self.on_event({"type": "ping_out", "call": to, "text": f"Pinging {to}: waiting for a Pumpkin Report..."})

    def handle(self, ev, now=None):
        now = now or time.time()
        if ev.get("type") == "id":
            self.grids[ev["call"]] = ev.get("grid", "")
            return
        if ev.get("type") != "message" or not ev.get("complete"):
            return
        p = parse(ev["text"])
        if not p:
            return
        kind, to, snr = p
        sender = ev.get("from", "?")
        if sender in ("?", self.call):
            return
        if to != self.call:
            self._overheard(kind, sender, to, snr, now)
            return
        my_snr = ev.get("snr")
        if kind == "ping":
            self.heard[sender] = my_snr
            self._log(sender, my_snr, None, now, two_way=False)
            self.on_event({"type": "ping_in", "call": sender, "snr": my_snr,
                           "text": f"PING from {sender} at {snr_txt(my_snr)} dB"
                                   + (": sending a Pumpkin Report" if self.auto_reply else "")})
            if self.auto_reply:
                self.send(report_text(my_snr, sender))
        elif kind == "report":
            if now - self.pinged.get(sender, 0) > REPLY_WITHIN_S:
                return                          # not an answer to our ping
            self.pinged.pop(sender, None)
            if self.auto_reply:
                self.send(report_text(my_snr, sender, final=True))
            self._contact(sender, snr, my_snr, now)
        elif kind == "final":
            self._contact(sender, snr, self.heard.get(sender, my_snr), now)

    def _overheard(self, kind, sender, to, snr, now):
        """Uranus network: a ping exchange between two other stations tells us that path is open."""
        if kind == "ping":
            return
        p = {"time": now, "heard": to, "heard_grid": self.grids.get(to, ""), "by": sender,
             "by_grid": self.grids.get(sender, ""), "snr": snr, "freq_hz": self.freq_hz, "submode": self.submode}
        try:
            os.makedirs(os.path.dirname(self.paths_path) or ".", exist_ok=True)
            with open(self.paths_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(p) + "\n")
        except OSError:
            pass
        self.on_event({"type": "path", "path": p, "text": f"Network: {sender} hears {to} at {snr:+d} dB"})

    def _contact(self, call, they_heard_me, i_heard_them, now):
        if now - self.done.get(call, 0) < 60:
            return
        self.done[call] = now
        c = self._log(call, i_heard_them, they_heard_me, now, two_way=True)
        self.on_event({"type": "report", "call": call, "contact": c, "text": describe(c)})

    def _log(self, call, i_heard_them, they_heard_me, now, two_way):
        grid = self.grids.get(call, "")
        c = {"time": now, "call": call, "grid": grid, "my_call": self.call, "my_grid": self.grid,
             "i_heard_them": None if i_heard_them is None else round(float(i_heard_them), 1),
             "they_heard_me": they_heard_me, "km": km_between(self.grid, grid) if grid else None,
             "freq_hz": self.freq_hz, "band": propagation.band_of(self.freq_hz) if self.freq_hz else "",
             "submode": self.submode, "two_way": two_way}
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(c) + "\n")
        except OSError:
            pass
        return c


def demo(level_ab=-18.0, level_ba=-22.0, call_a="8P5AB", grid_a="GK03", call_b="K1ABC", grid_b="FN42",
         submode="PUMPKIN-15", seed=None, path=None):
    """Two simulated stations ping each other through weak Pumpkin channels (every frame is really modulated
    and decoded). Returns the events station A sees, ending in its Pumpkin Report. No radio needed."""
    import tempfile

    import numpy as np

    from . import chat, pumpkin
    rng = np.random.default_rng(seed)
    path = path or os.path.join(tempfile.mkdtemp(prefix="uranus_ping_"), "contacts.jsonl")
    air = {"A": [], "B": []}
    seen_a, seen_b = [], []
    a = PingAgent(call_a, grid_a, air["A"].append, 144.495e6, submode, seen_a.append, path)
    b = PingAgent(call_b, grid_b, air["B"].append, 144.495e6, submode, seen_b.append, path + ".b")
    re_a, re_b = chat.Reassembler(), chat.Reassembler()

    def over_air(frm, call, grid, agent, re_, level, seen):
        while air[frm]:
            text = air[frm].pop(0)
            seen_a.append({"type": "tx" if frm == "A" else "rx_note", "text": f"{call}: {text}"})
            for _label, bits in chat.frames_for(text, call, grid, True):
                y = pumpkin.modulate(pumpkin.message_to_symbols(None, None, bits=bits), submode).astype(float)
                x = np.concatenate([np.zeros(12000), y, np.zeros(6000)])
                x += np.sqrt(np.mean(y ** 2) / (10 ** (level / 10) * 2500 * 2 / pumpkin.FS)) * \
                    rng.standard_normal(len(x))
                for m in pumpkin.decode_audio(x, submode, df_max=0.1 / pumpkin.SUBMODES[submode]):
                    for ev in re_.feed(m):
                        agent.handle(ev)
    a.ping(call_b)
    for _ in range(2):
        over_air("A", call_a, grid_a, b, re_b, level_ab, seen_b)
        over_air("B", call_b, grid_b, a, re_a, level_ba, seen_a)
    over_air("A", call_a, grid_a, b, re_b, level_ab, seen_b)
    return seen_a
