"""Frequencies the user adds on the faceplate: kept in my_frequencies.json beside uranus.toml and merged into
the band plan (status "mine"), so they appear in the dial lists, Bands and modes, and the scanner. WEFAX
frequencies (mode "wefax", assigned kHz in `mhz` / 1000) are listed only in the weather fax window."""
import json
import os

from . import freqplan

MODES = ("ft8", "ft4", "q65", "jt65", "jt9", "fst4", "fst4w", "wspr", "aprs", "pumpkin", "cucumber", "ur", "wefax")


def path(config_path):
    return os.path.join(os.path.dirname(os.path.abspath(config_path)), "my_frequencies.json")


def load(config_path):
    try:
        with open(path(config_path), encoding="utf-8") as f:
            items = json.load(f)
        return [i for i in items if isinstance(i, dict) and i.get("mode") in MODES and float(i.get("mhz", 0)) > 0]
    except (OSError, ValueError, TypeError):
        return []


def save(config_path, items):
    with open(path(config_path), "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)


def band_of(mhz):
    for b, (lo, hi) in freqplan.BAND_EDGES.items():
        if lo <= mhz <= hi:
            return b
    return ""


def check(mode, mhz):
    """'' if the entry can be added, else why not."""
    if mode not in MODES:
        return f"Unknown mode {mode}."
    if mode == "wefax":
        return "" if 0.1 <= mhz <= 30.0 else "WEFAX frequencies are HF (give the published frequency in MHz)."
    if not band_of(mhz):
        return f"{mhz:.4f} MHz is outside the amateur bands Uranus knows."
    return ""


def add(config_path, mode, mhz, note=""):
    why = check(mode, mhz)
    if why:
        return why
    items = load(config_path)
    if any(i["mode"] == mode and abs(float(i["mhz"]) - mhz) < 1e-6 for i in items):
        return "That frequency is already in your list."
    items.append({"band": band_of(mhz) or "", "mode": mode, "mhz": round(mhz, 6), "note": note.strip()[:60]})
    save(config_path, items)
    apply(config_path)
    return ""


def remove(config_path, mode, mhz):
    items = [i for i in load(config_path) if not (i["mode"] == mode and abs(float(i["mhz"]) - mhz) < 1e-6)]
    save(config_path, items)
    apply(config_path)


def apply(config_path):
    """Put the user's amateur-band frequencies into freqplan.PLAN (replacing earlier ones)."""
    freqplan.PLAN[:] = [f for f in freqplan.PLAN if f.status != "mine"]
    for i in load(config_path):
        if i["mode"] != "wefax" and band_of(float(i["mhz"])):
            freqplan.PLAN.append(freqplan.Freq(band_of(float(i["mhz"])), i["mode"], float(i["mhz"]), "All", "mine",
                                               i.get("note") or "added by you"))
