"""FT8 and WSPR audio, using WSJT-X's own reference encoders.

The tone sequences come from the `ft8code` and `wsprcode` programs that ship
with WSJT-X (sudo apt install wsjtx). Using the reference encoders guarantees
on-air compatibility; Uranus only turns the tones into audio and keys the rig.
"""

import glob
import os
import re
import shutil
import subprocess

import numpy as np

FS = 12000
FT8_COSTAS = [3, 1, 4, 0, 6, 5, 2]


class EncoderMissing(RuntimeError):
    pass


def _find(tool):
    """PATH, then $WSJTX_BIN, then the usual Windows install folders."""
    exe = shutil.which(tool)
    if exe:
        return exe
    dirs = [os.environ.get("WSJTX_BIN", "")]
    if os.name == "nt":
        dirs += [r"C:\WSJT\wsjtx\bin"] + glob.glob(r"C:\WSJT\*\bin") + \
                glob.glob(os.path.expandvars(r"%ProgramFiles%\wsjtx*\bin"))
    for d in dirs:
        for name in (tool, tool + ".exe"):
            p = os.path.join(d, name) if d else ""
            if p and os.path.isfile(p):
                return p
    return None


def _run(tool, message):
    exe = _find(tool)
    if not exe:
        raise EncoderMissing(f"'{tool}' not found - install WSJT-X "
                             "(Linux: sudo apt install wsjtx; Windows: set WSJTX_BIN to its bin folder)")
    return subprocess.run([exe, message], capture_output=True, text=True, timeout=20).stdout


def parse_tones(text, count, max_tone):
    """Collect the first `count` digits <= max_tone after the 'Channel symbols' header."""
    m = re.search(r"channel symbols", text, re.I)
    if not m:
        raise ValueError("no 'Channel symbols' section in encoder output")
    body = text[m.end():]
    body = body.split("\n", 1)[1] if "\n" in body else body
    digits = [int(c) for c in re.findall(r"\d", body)]
    tones = [d for d in digits if d <= max_tone][:count]
    if len(tones) != count:
        raise ValueError(f"expected {count} tones, got {len(tones)}")
    return tones


def ft8_tones(message):
    tones = parse_tones(_run("ft8code", message), 79, 7)
    for start in (0, 36, 72):
        if tones[start:start + 7] != FT8_COSTAS:
            raise ValueError("ft8code output failed Costas sync check")
    return tones


def wspr_tones(call, grid, dbm):
    return parse_tones(_run("wsprcode", f"{call} {grid} {dbm}"), 162, 3)


def gfsk(tones, nsps, spacing, f0, bt=None, fs=FS, amp=0.5):
    freq = np.repeat(np.asarray(tones, float) * spacing, nsps)
    if bt:
        sigma = nsps * np.sqrt(np.log(2)) / (2 * np.pi * bt)
        x = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
        g = np.exp(-0.5 * (x / sigma) ** 2)
        freq = np.convolve(np.pad(freq, len(x) // 2, mode="edge"), g / g.sum(), mode="valid")
    y = amp * np.sin(2 * np.pi * np.cumsum(f0 + freq) / fs)
    r = min(nsps // 8, 240)
    w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, r))
    y[:r] *= w
    y[-r:] *= w[::-1]
    return y.astype(np.float32)


def ft8_audio(message, f0=1500.0):
    """79 symbols x 0.16 s, 6.25 Hz spacing, GFSK BT=2 (12.64 s)."""
    return gfsk(ft8_tones(message), 1920, 6.25, f0, bt=2.0)


def wspr_audio(call, grid, dbm, f0=1500.0):
    """162 symbols x 8192/12000 s, 1.4648 Hz spacing (110.6 s). f0 = centre of signal."""
    spacing = FS / 8192
    return gfsk(wspr_tones(call, grid, dbm), 8192, spacing, f0 - 1.5 * spacing)
