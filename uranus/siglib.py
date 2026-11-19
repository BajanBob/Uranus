"""Signal ID that learns: what normally lives on each frequency at this station.

When you confirm an identification (or correct it), Uranus remembers it for that dial frequency and audio
offset. Next time, a signal that is usual there gains confidence ("usual here, confirmed 6 times"), and one
never seen there before is flagged NEW, so changes on a frequency you watch stand out.
"""
import json
import os
import time

from . import spots

PATH = os.path.join(os.path.dirname(spots.DEFAULT_PATH), "siglib.json")


def _key(dial_mhz, freq_hz):
    return f"{round(dial_mhz * 1000)}|{int(freq_hz // 100) * 100 if freq_hz else 'all'}"


def load(path=PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(lib, path=PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lib, f, indent=1)


def teach(dial_mhz, finding, correct=True, actual=None, path=PATH):
    """Record a confirmed (or corrected) identification. actual = the right name when it was wrong."""
    lib = load(path)
    e = lib.setdefault(_key(dial_mhz, finding.freq_hz), {"names": {}, "wrong": {}, "last": 0})
    if correct:
        e["names"][finding.name] = e["names"].get(finding.name, 0) + 1
    else:
        e["wrong"][finding.name] = e["wrong"].get(finding.name, 0) + 1
        if actual:
            e["names"][actual] = e["names"].get(actual, 0) + 1
    e["last"] = time.time()
    save(lib, path)
    return e


def annotate(findings, dial_mhz, path=PATH):
    """Adjust confidences and add 'usual here' / 'NEW here' notes. Returns the findings (re-sorted)."""
    lib = load(path)
    for f in findings:
        e = lib.get(_key(dial_mhz, f.freq_hz)) or lib.get(_key(dial_mhz, 0))
        f.new_here = False
        if not e:
            continue
        n_ok = e["names"].get(f.name, 0)
        n_bad = e["wrong"].get(f.name, 0)
        total = sum(e["names"].values())
        if n_ok:
            f.confidence = round(min(0.99, f.confidence + min(0.15, 0.03 * n_ok)), 2)
            f.reasons = [f"usual here: confirmed {n_ok} time(s)"] + list(f.reasons)
        if n_bad:
            f.confidence = round(max(0.05, f.confidence - min(0.3, 0.1 * n_bad)), 2)
            f.reasons = [f"marked wrong here {n_bad} time(s)"] + list(f.reasons)
        if total >= 3 and not n_ok and f.kind == "signal":
            f.new_here = True
            f.reasons = ["NEW here: not seen before on this frequency"] + list(f.reasons)
    findings.sort(key=lambda f: (f.kind != "signal", -f.confidence))
    return findings


def usual(dial_mhz, path=PATH):
    """Names confirmed anywhere on this dial, most often first."""
    lib = load(path)
    tally = {}
    for k, e in lib.items():
        if k.split("|")[0] == str(round(dial_mhz * 1000)):
            for n, c in e["names"].items():
                tally[n] = tally.get(n, 0) + c
    return sorted(tally.items(), key=lambda t: -t[1])
