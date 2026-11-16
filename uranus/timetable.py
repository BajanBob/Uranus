"""When to transmit and when only to listen and decode.

[schedule] in uranus.toml:
  mode = "continuous"   transmit all the time, decoding in the gaps between transmissions
         "cycle"        take turns: transmit for tx_minutes, then listen and decode for listen_minutes, repeat
         "hours"        by the hour: transmit in tx_hours, listen in listen_hours, pause in the others
  tx_minutes, listen_minutes   one of CHOICES (30 min ... 24 h)
  tx_hours, listen_hours       lists of hours 0-23 (an hour in both lists transmits, decoding in the gaps)
  clock = "local" or "utc"     which clock the hours are in
"""

import time

CHOICES = [30, 180, 360, 540, 720, 1440]          # minutes: 30 min, 3, 6, 9, 12, 24 hours
MODES = ("continuous", "cycle", "hours")


def label(minutes):
    minutes = int(minutes)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h"


def minutes_of(text):
    """'30 min' -> 30, '3 h' -> 180."""
    n, unit = str(text).split()[:2]
    return int(n) * (60 if unit.startswith("h") else 1)


def settings(cfg):
    sc = dict(cfg.get("schedule", {}))
    sc.setdefault("mode", "continuous")
    if sc["mode"] not in MODES:
        sc["mode"] = "continuous"
    sc["tx_minutes"] = int(sc.get("tx_minutes", 30))
    sc["listen_minutes"] = int(sc.get("listen_minutes", 180))
    sc["tx_hours"] = sorted({int(h) % 24 for h in sc.get("tx_hours", [])})
    sc["listen_hours"] = sorted({int(h) % 24 for h in sc.get("listen_hours", [])})
    sc["clock"] = "utc" if str(sc.get("clock", "local")).lower() == "utc" else "local"
    return sc


def _hour_phase(sc, t):
    h = (time.gmtime(t) if sc["clock"] == "utc" else time.localtime(t)).tm_hour
    if h in sc["tx_hours"]:
        return "tx"
    if h in sc["listen_hours"]:
        return "listen"
    return "off"


def _next_hour(t):
    """Start of the next whole hour (works for local and UTC: time zones here are whole hours or halves,
    and Barbados is a whole hour)."""
    lt = time.localtime(t)
    return t - lt.tm_min * 60 - lt.tm_sec - (t % 1) + 3600


def phase_at(cfg_or_sc, t, start):
    """('tx' | 'listen' | 'off', end_time or None) for time t, in a session that began at `start`."""
    sc = cfg_or_sc if "tx_hours" in cfg_or_sc and "mode" in cfg_or_sc else settings(cfg_or_sc)
    if sc["mode"] == "cycle":
        tx, rx = sc["tx_minutes"] * 60, sc["listen_minutes"] * 60
        k = (t - start) % (tx + rx)
        return ("tx", t + tx - k) if k < tx else ("listen", t + tx + rx - k)
    if sc["mode"] == "hours":
        ph, end = _hour_phase(sc, t), _next_hour(t)
        for _ in range(24):                        # run on through following hours in the same phase
            if _hour_phase(sc, end + 1) != ph:
                break
            end = _next_hour(end + 1)
        return ph, end
    return "tx", None


def describe(sc):
    sc = settings({"schedule": sc}) if "tx_hours" not in sc else sc
    if sc["mode"] == "cycle":
        return (f"Take turns: transmit for {label(sc['tx_minutes'])}, then listen and decode for "
                f"{label(sc['listen_minutes'])}, and repeat")
    if sc["mode"] == "hours":
        clk = "UTC" if sc["clock"] == "utc" else "local time"
        hrs = lambda hs: ", ".join(f"{h:02d}" for h in hs) or "none"      # noqa: E731
        return f"By the hour ({clk}): transmit {hrs(sc['tx_hours'])}; listen {hrs(sc['listen_hours'])}"
    return "Transmit all the time, decoding between transmissions"
