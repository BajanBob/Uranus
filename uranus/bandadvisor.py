"""Best band now: which band and mode to use, from what you are actually hearing plus the sun.

Evidence, strongest first:
  1. your own decodes in the last hour on each band (how many stations, how far, how recent)
  2. who has heard you (PSK Reporter), when available
  3. a rough maximum usable frequency (MUF) from the solar flux (F10.7) and whether it is day or night here,
     with a penalty for a disturbed geomagnetic field (Kp)
Solar numbers come from NOAA SWPC when the internet is up; without them Uranus uses a mid-cycle default and
says so. The MUF model is a rule of thumb, not a propagation prediction service.
"""
import json
import math
import time
import urllib.request

from . import freqplan, geo, propagation, spots

F107_URL = "https://services.swpc.noaa.gov/json/f107_cm_flux.json"
KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"
CENTRE_MHZ = {"160m": 1.84, "80m": 3.57, "60m": 5.36, "40m": 7.07, "30m": 10.14, "20m": 14.07, "17m": 18.1,
              "15m": 21.07, "12m": 24.92, "10m": 28.07, "6m": 50.31, "2m": 144.17}
_solar_cache = {"t": 0, "val": None}


def solar(timeout=5):
    """(sfi, kp, source). Cached for an hour."""
    if _solar_cache["val"] and time.time() - _solar_cache["t"] < 3600:
        return _solar_cache["val"]
    sfi = kp = None
    try:
        with urllib.request.urlopen(F107_URL, timeout=timeout) as r:
            rows = json.load(r)
        vals = [float(x["flux"]) for x in rows if x.get("flux") not in (None, "")]
        sfi = vals[-1] if vals else None
    except Exception:                             # noqa: BLE001
        pass
    try:
        with urllib.request.urlopen(KP_URL, timeout=timeout) as r:
            rows = json.load(r)
        kp = float(rows[-1][1])
    except Exception:                             # noqa: BLE001
        pass
    val = (sfi or 120.0, kp if kp is not None else 2.0,
           "NOAA SWPC" if sfi is not None else "default (no internet: SFI 120, Kp 2 assumed)")
    _solar_cache.update(t=time.time(), val=val)
    return val


def sun_elevation(lat, lon, t=None):
    """Solar elevation in degrees (good to about a degree)."""
    t = t or time.time()
    d = t / 86400.0 + 2440587.5 - 2451545.0
    g = math.radians((357.529 + 0.98560028 * d) % 360)
    q = (280.459 + 0.98564736 * d) % 360
    lam = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.00000036 * d)
    dec = math.asin(math.sin(eps) * math.sin(lam))
    ra = math.degrees(math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))) % 360
    gmst = (280.46061837 + 360.98564736629 * d) % 360
    ha = math.radians((gmst + lon - ra + 540) % 360 - 180)
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def muf(sfi, elevation, kp):
    """Rough 3000 km MUF in MHz: about 14 MHz at night, 22-35 MHz by day depending on solar flux."""
    day = max(0.0, min(1.0, (elevation + 6) / 30))           # twilight to mid-morning ramp
    m = 9 + 6 * (sfi / 100) ** 0.5 + day * (12 + 14 * max(0.0, (sfi - 70)) / 130)
    return m * (1 - 0.04 * max(0.0, kp - 4))


def advise(home_grid, spot_list=None, heard=None, sfi=None, kp=None, now=None, source=""):
    """Ranked [{band, score, mode, dial_mhz, reasons}]"""
    now = now or time.time()
    home = geo.grid_to_latlon(home_grid)
    if sfi is None:
        sfi, kp, source = solar()
    elev = sun_elevation(home[0], home[1], now)
    m = muf(sfi, elev, kp)
    spot_list = spot_list if spot_list is not None else spots.load(since_s=3600)
    by = {}
    for s in list(spot_list) + list(heard or []):
        b = propagation.band_of(s.get("freq_hz"))
        if b not in CENTRE_MHZ or now - s.get("time", 0) > 3600:
            continue
        e = by.setdefault(b, {"calls": set(), "km": 0, "recent": 0.0, "heard": 0})
        e["calls"].add(s.get("call"))
        if s.get("direction") == "heard":
            e["heard"] += 1
        w = math.exp(-(now - s.get("time", now)) / 1200)
        e["recent"] += w
        try:
            e["km"] = max(e["km"], geo.distance_km(home, geo.grid_to_latlon(s["grid"])))
        except Exception:                         # noqa: BLE001
            pass
    out = []
    for b, f in CENTRE_MHZ.items():
        reasons = []
        e = by.get(b)
        act = 0.0
        if e:
            act = min(1.0, 0.15 * len(e["calls"]) + 0.1 * e["recent"]) + min(0.3, e["km"] / 20000)
            reasons.append(f"you heard {len(e['calls'])} station(s) in the last hour" +
                           (f", furthest {e['km']:,.0f} km" if e["km"] else ""))
            if e["heard"]:
                reasons.append(f"{e['heard']} report(s) of you on PSK Reporter")
        if f < 30:
            r = f / m
            prop = max(0.0, 1 - abs(r - 0.8) / 0.6) if r <= 1.05 else max(0.0, 0.3 - (r - 1.05))
            if f < 8 and elev > 10:
                prop *= 0.4                       # daytime D-layer absorption on the low bands
                reasons.append("low band in daylight: absorbed by day")
            reasons.append(f"rough MUF {m:.0f} MHz ({'day' if elev > 0 else 'night'}, SFI {sfi:.0f}, Kp {kp:.0f})")
        else:
            prop = 0.15                           # 6 m / 2 m: openings come and go; trust the decodes
            reasons.append("VHF: open only during Es, tropo or TEP - follow what you hear")
        score = 0.65 * act + 0.35 * prop if e else 0.35 * prop
        mode = "FT8"
        dial = next((o.mhz for o in freqplan.options(b, "ft8")), f)
        out.append({"band": b, "score": round(score, 3), "mode": mode, "dial_mhz": dial, "reasons": reasons,
                    "heard_here": bool(e)})
    out.sort(key=lambda r: -r["score"])
    return {"ranked": out, "muf": round(m, 1), "sfi": sfi, "kp": kp, "sun_elevation": round(elev, 1),
            "solar_source": source}


def summary(res, n=3):
    lines = [f"Sun {res['sun_elevation']:+.0f}° · solar flux {res['sfi']:.0f} · Kp {res['kp']:.0f} "
             f"({res['solar_source']}) · rough MUF {res['muf']} MHz"]
    for i, r in enumerate(res["ranked"][:n], 1):
        lines.append(f"{i}. {freqplan.BAND_NAMES.get(r['band'], r['band'])}  {r['mode']} {freqplan.fmt(r['dial_mhz'])} MHz"
                     f"  ({r['score']:.0%}): " + "; ".join(r["reasons"][:2]))
    return "\n".join(lines)
