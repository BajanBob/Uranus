"""Propagation analyst: which propagation mode most likely carried each contact.

An explainable, evidence-weighted estimator. Each candidate mechanism gets a
score from what is known about it on 2 m and 70 cm:

  * path length (each mechanism has a characteristic distance range)
  * band (sporadic-E and TEP are strongly favoured on 2 m over 70 cm)
  * local solar time at the path midpoint and the month (Es season,
    meteor pre-dawn peak, evening TEP, overnight ducting)
  * path geometry (TEP needs a roughly north-south path across the
    geomagnetic equator)
  * the signal itself, when the URC decoder measured it: fading depth and
    phase wander (Doppler spread), and how steady the decodes were
  * signal strength for the distance (scatter is weak; ducts, Es and TEP are strong)

The scores are normalised into probabilities and returned with the reasons.
This is a rule-based expert estimate, not a trained neural model: there is
no labelled propagation data to train one yet. The spot log it reads is the
data such a model could later be trained on.
"""

import math
import time

from . import geo

MODES = {
    "los": "Line of sight",
    "tropo_scatter": "Tropospheric scatter",
    "ducting": "Tropospheric ducting",
    "aircraft": "Aircraft scatter",
    "meteor": "Meteor scatter",
    "es": "Sporadic-E",
    "tep": "Trans-equatorial (TEP)",
}

# characteristic path length: (median km, spread in decades)
DIST = {"tropo_scatter": (250, 0.30), "ducting": (600, 0.30), "aircraft": (450, 0.22),
        "meteor": (1300, 0.15), "es": (1900, 0.09), "tep": (5500, 0.15)}

PRIOR = {"2m": {"los": 1.0, "tropo_scatter": 1.0, "ducting": 0.8, "aircraft": 0.5, "meteor": 0.35,
                "es": 0.45, "tep": 0.2},
         "70cm": {"los": 1.0, "tropo_scatter": 1.0, "ducting": 0.9, "aircraft": 0.55, "meteor": 0.12,
                  "es": 0.01, "tep": 0.03}}


def band_of(freq_hz):
    f = (freq_hz or 0) / 1e6
    if 144 <= f <= 148:
        return "2m"
    if 420 <= f <= 450:
        return "70cm"
    return "?"


def dip_equator_lat(lon):
    """Very rough geomagnetic (dip) equator latitude, degrees. Good to ~5 deg."""
    pts = [(-180, 0), (-120, -2), (-90, -5), (-75, -12), (-60, -13), (-45, -12), (-30, -8),
           (0, 9), (30, 10), (60, 9), (90, 8), (120, 6), (150, 2), (180, 0)]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= lon <= x1:
            return y0 + (y1 - y0) * (lon - x0) / (x1 - x0)
    return 0.0


def _bump(x, lo, hi, soft):
    """1 inside [lo, hi], falling off smoothly outside."""
    if lo <= x <= hi:
        return 1.0
    d = lo - x if x < lo else x - hi
    return math.exp(-(d / soft) ** 2)


def _logn(d_km, med, spread):
    return math.exp(-0.5 * ((math.log10(max(d_km, 1)) - math.log10(med)) / spread) ** 2)


def solar_hour(utc_ts, lon):
    t = time.gmtime(utc_ts)
    return (t.tm_hour + t.tm_min / 60 + lon / 15) % 24


def classify(home, remote, band, utc_ts, snr=None, fade_db=None, spread_hz=None, steady=None,
             ant_heights=(10.0, 10.0)):
    """home/remote: (lat, lon). Returns [(mode_key, prob, [reasons])] sorted, best first."""
    d = geo.distance_km(home, remote)
    mid_lat, mid_lon = (home[0] + remote[0]) / 2, (home[1] + remote[1]) / 2
    hr = solar_hour(utc_ts, mid_lon)
    hh = f"{int(hr):02d}:00 local solar time"
    month = time.gmtime(utc_ts).tm_mon
    north = mid_lat >= 0
    horizon = 4.12 * (math.sqrt(ant_heights[0]) + math.sqrt(ant_heights[1]))
    pri = PRIOR.get(band, PRIOR["2m"])
    s, why = {}, {k: [] for k in MODES}

    # distance
    s["los"] = 1.0 if d <= horizon * 1.3 else math.exp(-((d - horizon * 1.3) / horizon) ** 2)
    for k, (med, sp) in DIST.items():
        s[k] = _logn(d, med, sp)
    if d <= horizon * 1.3:
        why["los"].append(f"{d:.0f} km is within the radio horizon (~{horizon:.0f} km)")
    for k in ("tropo_scatter", "ducting", "aircraft", "meteor", "es", "tep"):
        if s[k] > 0.6:
            why[k].append(f"{d:.0f} km fits its usual range")

    # band
    for k in s:
        s[k] *= pri.get(k, 0.5)
    if band == "70cm":
        why["ducting"].append("ducting favours 70 cm as much as 2 m")
    if band == "2m":
        why["es"].append("sporadic-E reaches 2 m (almost never 70 cm)")

    # time of day and season
    night = _bump(hr, 18, 24, 2.5) if hr >= 12 else _bump(hr, 0, 9, 2.5)
    s["ducting"] *= 0.6 + 0.6 * night
    if night > 0.6:
        why["ducting"].append(f"evening, night or early morning ({hh}), when inversions form")
    s["meteor"] *= 0.5 + 0.8 * _bump(hr, 3, 10, 2)
    if _bump(hr, 3, 10, 2) > 0.6:
        why["meteor"].append(f"pre-dawn/morning meteor peak ({hh})")
    s["aircraft"] *= 0.4 + 0.6 * _bump(hr, 6, 23, 1.5)
    es_day = _bump(hr, 9, 21, 2)
    es_season = _bump(month, 5, 8, 1) if north else max(_bump(month, 11, 12, 1), _bump(month, 1, 1, 1))
    s["es"] *= es_day * (0.25 + 0.75 * es_season)
    if es_season > 0.6:
        why["es"].append("inside the sporadic-E season")
    s["tep"] *= 0.2 + 0.8 * _bump(hr, 17, 23.5, 1.5)
    if _bump(hr, 17, 23.5, 1.5) > 0.6:
        why["tep"].append(f"evening TEP window ({hh})")

    # TEP geometry: opposite sides of the dip equator, path roughly north-south
    e1, e2 = dip_equator_lat(home[1]), dip_equator_lat(remote[1])
    opposite = (home[0] - e1) * (remote[0] - e2) < 0
    brg = geo.bearing_deg(home, remote)
    ns = min(abs(brg - 0), abs(brg - 180), abs(brg - 360)) < 40
    if opposite and ns:
        why["tep"].append("north-south path across the geomagnetic equator")
    else:
        s["tep"] *= 0.05

    # the signal itself
    if fade_db is not None and spread_hz is not None:
        rough = min(1.0, fade_db / 6.0 + spread_hz / 0.6)
        for k, w in (("aircraft", 1.0), ("meteor", 1.0), ("tep", 0.8), ("es", 0.3)):
            s[k] *= 0.4 + 1.2 * rough * w
        for k in ("los", "ducting", "tropo_scatter"):
            s[k] *= 1.3 - 0.8 * rough
        if rough > 0.5:
            for k in ("aircraft", "meteor", "tep"):
                why[k].append(f"fast fading/Doppler measured ({fade_db:.1f} dB, {spread_hz:.2f} Hz)")
        else:
            for k in ("ducting", "tropo_scatter", "los"):
                why[k].append(f"steady signal measured ({fade_db:.1f} dB fades)")
    if steady is not None:
        for k in ("meteor", "aircraft"):
            s[k] *= 1.3 - 0.7 * steady
        for k in ("ducting", "tropo_scatter", "los"):
            s[k] *= 0.7 + 0.6 * steady
        if steady > 0.6:
            why["ducting"].append("heard in many consecutive slots")
        elif steady < 0.3:
            why["meteor"].append("heard only in occasional slots")

    # strength for the distance: scatter is weak, ducts/Es/TEP can be strong
    if snr is not None and d > 300:
        strong = _bump(snr, -18, 40, 4)
        s["tropo_scatter"] *= 1.1 - 0.6 * strong
        for k in ("ducting", "es", "tep"):
            s[k] *= 0.8 + 0.6 * strong
        if strong > 0.6:
            why["ducting"].append(f"strong ({snr:+.0f} dB) for {d:.0f} km")

    tot = sum(s.values()) or 1.0
    out = [(k, v / tot, why[k]) for k, v in s.items()]
    out.sort(key=lambda x: -x[1])
    return out


def band_summary(stations):
    """Average mode probabilities per band over the given (recent) stations."""
    res = {}
    for st in stations:
        b = st.get("band", "?")
        r = res.setdefault(b, {"n": 0, "max_km": 0, "probs": {k: 0.0 for k in MODES}})
        r["n"] += 1
        r["max_km"] = max(r["max_km"], st["km"])
        for k, p in st.get("prop", {}).items():
            r["probs"][k] += p
    for r in res.values():
        if r["n"]:
            r["probs"] = {k: v / r["n"] for k, v in r["probs"].items()}
        r["top"] = max(r["probs"], key=r["probs"].get) if r["n"] else None
    return res
