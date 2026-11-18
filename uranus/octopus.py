"""Octopus - daily propagation analysis from Uranus's own spot log (and PSK Reporter spots it uploaded).

Research emphasis: 2 m and 70 cm from the Caribbean (tropospheric ducting over the trade-wind
inversion, TEP, Es, aircraft and meteor scatter). HF spots are summarised as F2 context.

    python -m uranus octopus                      # yesterday + today (UTC) from out/spots.jsonl
    python -m uranus octopus --day 2026-11-16     # one UTC day
    python -m uranus octopus --csv spots.csv      # a transcribed / exported table

Writes research/octopus/<day>/report.md and spots.csv. Weather and space-weather context can be added in
research/octopus/<day>/context.md, which is included in the report when present.
"""

import csv
import datetime as dt
import json
import os
import time

from . import geo, propagation, spotdb
from .sanity import suspect

VHF = ("6m", "2m", "1.25m", "70cm")


def load_jsonl(path, t0, t1):
    out = []
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                s = json.loads(line)
            except ValueError:
                continue
            if t0 <= s.get("time", 0) < t1:
                out.append(s)
    return out


def load_csv(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            s = {"call": row["call"], "grid": row["grid"], "snr": float(row["snr"]),
                 "freq_hz": float(row.get("freq_hz") or 14_075_000), "mode": row.get("mode", "FT8"),
                 "time": float(row.get("time") or 0), "direction": row.get("direction", "rx")}
            if row.get("best"):
                s["best"] = float(row["best"])
            out.append(s)
    return out


def analyse(spots, home_grid, title=""):
    home = geo.grid_to_latlon(home_grid)
    by = {}
    for s in spots:
        try:
            ll = geo.grid_to_latlon(s["grid"])
        except (ValueError, KeyError, IndexError):
            continue
        band = propagation.band_of(s.get("freq_hz"))
        k = (s["call"], band)
        st = by.setdefault(k, {"call": s["call"], "grid": s["grid"], "band": band, "n": 0, "snrs": [],
                               "best": -99.0, "times": [], "ll": ll, "mode": s.get("mode", "")})
        st["n"] += 1
        st["snrs"].append(s["snr"])
        st["best"] = max(st["best"], s.get("best", s["snr"]))
        if s.get("time"):
            st["times"].append(s["time"])
    rows = []
    for st in by.values():
        km = geo.distance_km(home, st["ll"])
        brg = geo.bearing_deg(home, st["ll"])
        t = max(st["times"]) if st["times"] else time.time()
        res = propagation.classify(home, st["ll"], st["band"], t, snr=st["snrs"][-1])
        why = suspect(st["call"], st["grid"])
        rows.append({**st, "km": round(km), "brg": round(brg), "last_snr": st["snrs"][-1],
                     "likely": propagation.MODES[res[0][0]], "why": "; ".join(res[0][2][:2]), "suspect": why})
    rows.sort(key=lambda r: (r["band"] not in VHF, -r["km"]))
    return rows


def _region(ll, km):
    lat, lon = ll
    if km < 2500:
        return "Caribbean basin and nearby (under 2,500 km)"
    if lon < -30:
        return "South America" if lat < 12 else "North and Central America"
    if lat >= 35 and lon <= 45:
        return "Europe"
    if lon > 45 and lat >= 35:
        return "Central Asia"
    if 12 <= lat < 35 and 30 <= lon <= 63:
        return "Middle East"
    if lon > 63:
        return "Asia / Pacific"
    return "Africa and Indian Ocean"


def report(rows, home_grid, day, context="", source="", spots=None, window=None):
    good = [r for r in rows if not r["suspect"]]
    bad = [r for r in rows if r["suspect"]]
    vhf = [r for r in good if r["band"] in VHF]
    hf = [r for r in good if r["band"] not in VHF]
    L = [f"# Octopus daily analysis - {day} - 8P5AB, {home_grid} (Barbados)", ""]
    if source:
        L += [f"Source: {source}", ""]
    L += ["## 2 m and 70 cm (research focus)", ""]
    if not vhf:
        L += ["No 2 m, 1.25 m or 70 cm stations were decoded in this period. This is a baseline (null) result: "
              "it records that the VHF/UHF paths monitored were closed, or that the station was not listening "
              "on those bands.", ""]
    else:
        L += ["| Station | Band | Grid | km | Bearing | SNR | Best | Likely mode | Evidence |", "|---|---|---|---|---|---|---|---|---|"]
        for r in vhf:
            L.append(f"| {r['call']} | {r['band']} | {r['grid']} | {r['km']:,} | {r['brg']}° | {r['last_snr']:+.0f} | "
                     f"{r['best']:+.0f} | {r['likely']} | {r['why']} |")
        L.append("")
    if hf:
        bands = sorted({r["band"] for r in hf})
        L += [f"## HF context ({', '.join(bands)})", ""]
        L += [f"- Stations: **{len(hf)}** (after removing {len(bad)} suspect decode(s))",
              f"- Distance: {min(r['km'] for r in hf):,} to {max(r['km'] for r in hf):,} km, "
              f"median {sorted(r['km'] for r in hf)[len(hf) // 2]:,} km",
              f"- SNR (last heard): {min(r['last_snr'] for r in hf):+.0f} to {max(r['last_snr'] for r in hf):+.0f} dB"]
        regions = {}
        for r in hf:
            regions.setdefault(_region(r["ll"], r["km"]), []).append(r)
        L += ["", "| Region | Stations | Distance (km) | Best SNR | Examples |", "|---|---|---|---|---|"]
        for reg, rs in sorted(regions.items(), key=lambda x: -len(x[1])):
            ex = ", ".join(r["call"] for r in sorted(rs, key=lambda r: -r["km"])[:4])
            L.append(f"| {reg} | {len(rs)} | {min(r['km'] for r in rs):,}-{max(r['km'] for r in rs):,} | "
                     f"{max(r['best'] for r in rs):+.0f} | {ex} |")
        L += ["", "Mode: F2-layer skywave throughout (tropospheric ducting and TEP do not apply on HF).", ""]
    L += openings_section(spots, window)
    L += fields_section(good)
    L += ["## Anomalies", ""]
    if bad:
        L += ["Suspect decodes (kept out of the analysis):", ""]
        L += [f"- **{r['call']}** {r['grid']} {r['last_snr']:+.0f} dB - {r['suspect']}" for r in bad]
        L.append("")
    strong = [r for r in good if r["best"] >= 15 and r["km"] > 2000]
    if strong:
        L += ["Unusually strong for the distance:", ""]
        L += [f"- **{r['call']}** {r['grid']}, {r['km']:,} km, best {r['best']:+.0f} dB (last {r['last_snr']:+.0f} dB)"
              for r in strong]
        L.append("")
    if not bad and not strong:
        L += ["None found.", ""]
    if context:
        L += ["## Weather and space weather", "", context.strip(), ""]
    L += ["## Method", "",
          "Spots: Uranus decodes (WSJT-X jt9 for FT8), uploaded live to PSK Reporter. Distances and bearings are "
          "great-circle from the 6-character grid. Propagation mode is an evidence-weighted estimate; on HF it is "
          "F2 skywave with an estimated hop count. Suspect decodes: WSJT-X '?' flag, grids in open ocean, or "
          "Antarctic grids for non-Antarctic calls.", ""]
    return "\n".join(L)


def openings_section(spots, window=None, width=120, max_gap=2):
    """Band openings found by the recursive slot walk in spotdb (needs spot times)."""
    timed = [s for s in spots or [] if s.get("time")]
    if not timed:
        return []
    t0, t1 = window or (min(s["time"] for s in timed), max(s["time"] for s in timed) + 1)
    t0 -= t0 % width
    db = spotdb.from_spots(timed)
    L = ["## Band openings (UTC)", "",
         f"A band counts as open while it keeps producing spots; a gap of more than {max_gap * width // 60} "
         "minutes ends an opening.", "",
         "| Band | Open | Stations | Spots | Best SNR |", "|---|---|---|---|---|"]
    found = False
    for band in spotdb.bands(db, t0, t1):
        for o in spotdb.openings(db, band, t0, t1, width, max_gap):
            found = True
            L.append(f"| {band} | {spotdb.hhmm(o['start'])}-{spotdb.hhmm(o['stop'])} | {o['stations']} | "
                     f"{o['spots']} | {o['best_snr']:+.0f} |")
    db.close()
    return L + [""] if found else []


def fields_section(rows, top=8):
    """Maidenhead fields heard, each with its busiest squares (recursive grid tree)."""
    tree = geo.grid_tree([r["grid"] for r in rows])
    if not tree:
        return []
    L = ["## Grid fields heard", "", "| Field | Stations | Busiest squares |", "|---|---|---|"]
    for f in tree[:top]:
        sq = ", ".join(f"{c['grid']} ({c['count']})" for c in f["children"][:4])
        L.append(f"| {f['grid']} | {f['count']} | {sq} |")
    return L + [""]


def write(rows, outdir):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "spots.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["call", "band", "grid", "km", "bearing", "last_snr", "best_snr", "likely_mode", "suspect"])
        for r in rows:
            w.writerow([r["call"], r["band"], r["grid"], r["km"], r["brg"], r["last_snr"], r["best"], r["likely"],
                        r["suspect"]])


def run(home_grid, spot_path="out/spots.jsonl", day=None, csv_path=None, root=os.path.join("research", "octopus")):
    if csv_path:
        spots, src = load_csv(csv_path), f"table {os.path.basename(csv_path)}"
        day = day or dt.date.today().isoformat()
        window = None
    else:
        d = dt.date.fromisoformat(day) if day else dt.datetime.now(dt.timezone.utc).date()
        t1 = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() + 86400
        t0 = t1 - (86400 if day else 2 * 86400)
        spots, src = load_jsonl(spot_path, t0, t1), f"Uranus spot log {spot_path}"
        window = (t0, t1)
        day = d.isoformat()
    rows = analyse(spots, home_grid)
    outdir = os.path.join(root, day)
    ctx_path = os.path.join(outdir, "context.md")
    ctx = open(ctx_path, encoding="utf-8").read() if os.path.exists(ctx_path) else ""
    write(rows, outdir)
    text = report(rows, home_grid, day, ctx, src, spots=spots, window=window)
    with open(os.path.join(outdir, "report.md"), "w", encoding="utf-8") as f:
        f.write(text)
    return os.path.join(outdir, "report.md"), rows
