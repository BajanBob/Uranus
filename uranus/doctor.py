"""Interference doctor: a guided hunt for the noise that hides weak signals.

Each step changes one thing at the station (charger out, chokes on, lamps off, antenna off) and Uranus
measures the receiver for 10 seconds: overall noise level, mains hum, switching-supply lines and clicks.
Comparing every step with the first one shows what helped and by how much.
"""
import numpy as np

STEPS = [
    ("baseline", "As normal", "Leave everything as it is now. Tune to a quiet frequency (no signals) on the band "
                              "you care about."),
    ("battery", "Laptop on battery", "Unplug the laptop charger (and any USB hub power supply). Leave the radio on."),
    ("chokes", "Ferrite chokes on", "Plug the charger back in, with clip-on ferrite chokes on the charger lead and "
                                    "the USB audio cable, close to the laptop."),
    ("lamps", "Lamps and chargers off", "Switch off LED lamps, phone chargers, the TV and other gadgets in the "
                                        "house for a moment."),
    ("antenna", "Antenna disconnected", "Disconnect the antenna (or switch to a dummy load). Noise that stays "
                                        "comes from inside the radio, the computer or the cables, not the air."),
]


def measure(x, fs=12000):
    from . import sigint
    from scipy.signal import welch
    x = np.asarray(x, float)
    f, p = welch(x, fs, nperseg=4096)
    band = (f > 300) & (f < 2700)
    floor_db = float(10 * np.log10(np.median(p[band]) + 1e-20))
    h = sigint.hum(x)
    c = sigint.comb(x)
    imp = sigint.impulses(x)
    hum_db = 0.0
    if h:
        try:
            hum_db = float(h.reasons[1].split(",")[1].split("dB")[0])
        except (IndexError, ValueError):
            hum_db = 10.0
    clicks = 0.0
    if imp:
        try:
            clicks = float(imp.reasons[1].split()[1])
        except (IndexError, ValueError):
            clicks = 1.0
    lines = int(c.reasons[0].split()[0]) if c else 0
    return {"floor_db": round(floor_db, 1), "hum_db": round(hum_db, 1), "comb_lines": lines,
            "clicks_per_s": round(clicks, 1), "level_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)), 1)}


def compare(base, now, label):
    """What changed against the baseline, in plain words."""
    out = []
    d = base["floor_db"] - now["floor_db"]
    if d >= 3:
        out.append(f"noise floor {d:.0f} dB lower")
    elif d <= -3:
        out.append(f"noise floor {-d:.0f} dB higher")
    if base["hum_db"] and now["hum_db"] < base["hum_db"] - 6:
        out.append("mains hum gone or much weaker" if now["hum_db"] == 0 else
                   f"hum {base['hum_db'] - now['hum_db']:.0f} dB weaker")
    if base["comb_lines"] and now["comb_lines"] < base["comb_lines"] / 2:
        out.append("switching-supply lines gone or reduced")
    if base["clicks_per_s"] and now["clicks_per_s"] < base["clicks_per_s"] / 2:
        out.append("clicks reduced")
    if not out:
        return f"{label}: no clear change"
    return f"{label}: " + ", ".join(out)


def verdict(results):
    """results: {step_key: measurement}. A short diagnosis."""
    base = results.get("baseline")
    if not base:
        return "Measure the baseline first."
    lines = []
    if base["hum_db"] or base["comb_lines"] or base["clicks_per_s"]:
        bits = []
        if base["hum_db"]:
            bits.append(f"mains hum {base['hum_db']:.0f} dB")
        if base["comb_lines"]:
            bits.append(f"{base['comb_lines']} switching-supply lines")
        if base["clicks_per_s"]:
            bits.append(f"{base['clicks_per_s']:.0f} clicks a second")
        lines.append("At the start: " + ", ".join(bits) + ".")
    best, gain = None, 0.0
    for key, label, _ in STEPS[1:]:
        m = results.get(key)
        if not m:
            continue
        lines.append(compare(base, m, label))
        g = (base["floor_db"] - m["floor_db"]) + (base["hum_db"] - m["hum_db"]) / 2
        if key != "antenna" and g > gain:
            best, gain = label, g
    ant = results.get("antenna")
    if ant:
        if base["floor_db"] - ant["floor_db"] < 3:
            lines.append("With the antenna off the noise stayed: it is made at the station (radio, computer, "
                         "cables), so chokes, battery power and a common ground are the cure.")
        else:
            lines.append("The noise dropped with the antenna off: it arrives through the antenna, from the "
                         "neighbourhood or the house wiring. Try moving the antenna away from the house.")
    if best and gain >= 3:
        lines.append(f"Biggest improvement: {best}. Make that change permanent.")
    return "\n".join(lines)
