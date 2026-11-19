"""Mission profiles: one choice sets Uranus up for a job.

Each profile says what to listen to, what the timetable does, which tools to open and how they are preset.
It never ticks a transmit band or mode for you (that stays your licence decision in Bands and modes); a
profile with transmit windows uses whatever you have ticked there, and the Apply screen lists every change
before anything is saved.
"""
from dataclasses import dataclass, field


@dataclass
class Mission:
    key: str
    name: str
    summary: str
    receive: dict                       # [receive] mode / submode / dial_mhz
    timetable: dict                     # [timetable] enabled / outside / windows
    tools: list = field(default_factory=list)       # windows to open: wefax, scanner, signal_id, chat, map, best
    wefax: dict = field(default_factory=dict)       # station call, autopilot
    scanner: dict = field(default_factory=dict)     # bands, modes, dwell_min
    extras: dict = field(default_factory=dict)      # smart_beacon, speak, noise_filter
    tips: list = field(default_factory=list)

    def changes(self):
        """Plain-English list of what Apply will change."""
        rx = self.receive
        out = [f"Decode {rx['submode']} on {rx['dial_mhz']} MHz"]
        tt = self.timetable
        if tt.get("enabled"):
            out.append("Timetable on: " + "; ".join(tt["windows"]))
        else:
            out.append("Timetable off (ON AIR transmits all the time; Listen + decode listens all the time)")
        if self.wefax:
            out.append(f"Weather fax: {self.wefax['call']}" + (", autopilot on" if self.wefax.get("autopilot") else ""))
        if self.scanner:
            out.append("Scanner: " + ", ".join(self.scanner["bands"]) + " · " + ", ".join(
                m.upper() for m in self.scanner["modes"]) + f" · stop up to {self.scanner.get('dwell_min', 3)} min")
        ex = self.extras
        if "smart_beacon" in ex:
            out.append("Smart beacon " + ("on" if ex["smart_beacon"] else "off"))
        if "speak" in ex:
            out.append("Spoken alerts " + ("on" if ex["speak"] else "off"))
        if "noise_filter" in ex:
            out.append("Noise filter " + ("on" if ex["noise_filter"] else "off"))
        if self.tools:
            out.append("Opens: " + ", ".join(TOOL_NAMES.get(t, t) for t in self.tools))
        return out


TOOL_NAMES = {"wefax": "Weather fax", "scanner": "Scanner", "signal_id": "Signal ID", "chat": "Chat and ping",
              "map": "Station map", "best": "Best band now", "health": "Station health"}

MISSIONS = [
    Mission("hurricane", "Hurricane watch",
            "Storm season: tropical weather charts from New Orleans, ready to ping and chat with other islands, "
            "listening all day. Receive only unless you press ON AIR.",
            {"mode": "pumpkin", "submode": "PUMPKIN-60", "dial_mhz": 144.490},
            {"enabled": True, "outside": "listen", "windows": ["00:00-23:59 listen"]},
            tools=["wefax", "chat", "health"],
            wefax={"call": "NMG", "autopilot": True},
            extras={"speak": True, "noise_filter": True, "smart_beacon": False},
            tips=["Run on battery so mains power cuts and charger hum don't matter.",
                  "Agree a Pumpkin chat frequency and even/odd slots with the other islands before the storm.",
                  "Charts help you watch the weather; follow official warnings."]),
    Mission("fieldday", "Field day",
            "Portable operation: FT8 on 20 m with the scanner ready across the HF bands, transmitting every "
            "10 minutes in daylight with whatever you ticked in Bands and modes.",
            {"mode": "auto", "submode": "AUTO", "dial_mhz": 14.074},
            {"enabled": True, "outside": "listen", "windows": ["08:00-20:00 transmit 10", "20:00-23:59 listen"]},
            tools=["scanner", "best"],
            scanner={"bands": ["40m", "20m", "17m", "15m", "10m"], "modes": ["ft8", "ft4"], "dwell_min": 3},
            extras={"smart_beacon": True, "noise_filter": True},
            tips=["Set the power and SWR limit for your portable antenna in Station setup."]),
    Mission("maritime", "Maritime",
            "Coastal and sea: weather fax autopilot plus Signal ID on watch for NAVTEX, RTTY weather and other "
            "utility signals.",
            {"mode": "auto", "submode": "AUTO", "dial_mhz": 14.074},
            {"enabled": False, "outside": "listen", "windows": []},
            tools=["wefax", "signal_id"],
            wefax={"call": "NMG", "autopilot": True},
            extras={"noise_filter": True},
            tips=["Pick the coast station for your waters in Weather fax (NMF Boston, NMC Point Reyes ...)."]),
    Mission("dx", "DX hunt",
            "Long-distance hunting: Best band now picks the band, the scanner sweeps the open HF bands for FT8, "
            "FT4 and JT65, and AUTO decodes everything heard.",
            {"mode": "auto", "submode": "AUTO", "dial_mhz": 14.074},
            {"enabled": True, "outside": "listen", "windows": ["00:00-23:59 listen"]},
            tools=["best", "scanner", "map"],
            scanner={"bands": ["20m", "17m", "15m", "12m", "10m"], "modes": ["ft8", "ft4", "jt65"], "dwell_min": 3},
            extras={"noise_filter": True}),
    Mission("overnight", "Overnight beacon",
            "Unattended beacon at night: transmits every 10 minutes from 22:00 to 06:00 (less often when the "
            "band is dead), listens by day. Tick WSPR or Pumpkin in Bands and modes.",
            {"mode": "pumpkin", "submode": "PUMPKIN-60", "dial_mhz": 144.490},
            {"enabled": True, "outside": "listen", "windows": ["22:00-06:00 transmit 10", "06:00-22:00 listen"]},
            tools=["health"],
            extras={"smart_beacon": True, "noise_filter": True},
            tips=["WSPR asks for about 20% transmit time; 10-minute spacing stays well under it."]),
    Mission("vhfprop", "2 m propagation watch",
            "VHF openings: FT8 and Q65 on 2 m with AUTO, the station map and a transmit every 15 minutes in the "
            "evening when tropo ducting is most likely.",
            {"mode": "auto", "submode": "AUTO", "dial_mhz": 144.174},
            {"enabled": True, "outside": "listen", "windows": ["17:00-23:59 transmit 15", "00:00-17:00 listen"]},
            tools=["map", "best"],
            extras={"smart_beacon": True, "noise_filter": True}),
]
BY_KEY = {m.key: m for m in MISSIONS}


def find(text):
    """Mission by key or (part of) its name: 'hurricane', 'field day', 'DX'."""
    t = text.strip().lower().replace("-", " ")
    for m in MISSIONS:
        if t in (m.key, m.name.lower()) or t.replace(" ", "") == m.key:
            return m
    for m in MISSIONS:
        if t and (t in m.name.lower() or m.key.startswith(t.replace(" ", ""))):
            return m
    return None


def config_changes(m):
    """{(section, key): value} for uranus.toml."""
    rx, tt = m.receive, m.timetable
    ch = {("receive", "mode"): rx["mode"], ("receive", "submode"): rx["submode"],
          ("receive", "dial_mhz"): rx["dial_mhz"], ("timetable", "enabled"): bool(tt.get("enabled")),
          ("timetable", "outside"): tt.get("outside", "listen"), ("mission", "name"): m.key}
    if tt.get("windows"):
        ch[("timetable", "windows")] = list(tt["windows"])
    if m.wefax:
        ch[("wefax", "station")] = m.wefax["call"]
        ch[("wefax", "autopilot")] = bool(m.wefax.get("autopilot"))
    if m.scanner:
        ch[("scanner", "bands")] = list(m.scanner["bands"])
        ch[("scanner", "modes")] = list(m.scanner["modes"])
        ch[("scanner", "dwell_min")] = m.scanner.get("dwell_min", 3)
    for k, sec in (("smart_beacon", ("beacon", "smart")), ("speak", ("access", "speak")),
                   ("noise_filter", ("receive", "noise_filter"))):
        if k in m.extras:
            ch[sec] = bool(m.extras[k])
    return ch


def current(cfg):
    return BY_KEY.get(cfg.get("mission", {}).get("name", ""))
