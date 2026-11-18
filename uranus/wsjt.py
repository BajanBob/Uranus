"""FT8 and WSPR audio, using WSJT-X's own reference encoders.

The tone sequences come from the `ft8code`, `ft4code` and `wsprcode` programs that ship
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
# On Windows, run jt9 / wsprd / ft8code etc. without flashing a console window.
_HIDE = {"creationflags": 0x08000000, "stdin": subprocess.DEVNULL} if os.name == "nt" else {}
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
    return subprocess.run([exe, message], capture_output=True, text=True, timeout=20, **_HIDE).stdout


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


FT4_COSTAS = ([0, 1, 3, 2], [1, 0, 2, 3], [2, 3, 1, 0], [3, 2, 0, 1])     # at symbols 0, 33, 66, 99


def ft4_tones(message):
    """105 channel symbols as ft4code prints them: ramp (R), 103 symbols with four Costas arrays, ramp (R)."""
    tones = parse_tones(_run("ft4code", message), 105, 3)
    if tones[0] != 0 or tones[-1] != 0:
        raise ValueError("ft4code output: expected ramp symbols at both ends")
    for k, start in enumerate((1, 34, 67, 100)):
        if tones[start:start + 4] != FT4_COSTAS[k]:
            raise ValueError("ft4code output failed Costas sync check")
    return tones


Q65_SYNC = 22                            # Q65 channel: 85 symbols, 22 of them the sync tone (0)


def q65_tones(message):
    """85 Q65 channel symbols as q65code prints them: tone 0 = sync, data tones 1-64."""
    text = _run("q65code", message)
    m = re.search(r"channel symbols[^\n]*\n", text, re.I)
    if not m:
        raise ValueError("no 'Channel symbols' section in q65code output")
    tones = [int(v) for v in re.findall(r"\d+", text[m.end():])][:85]   # two-digit tones: read whole numbers
    if len(tones) != 85 or max(tones) > 64 or tones.count(0) != Q65_SYNC:
        raise ValueError("q65code output failed the sync check")
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


def ft4_audio(message, f0=1500.0):
    """105 symbols x 48 ms (5.04 s), 20.833 Hz spacing, GFSK BT=1; the first and last symbol ramp the power
    up and down, as WSJT-X does."""
    y = gfsk(ft4_tones(message), 576, FS / 576, f0, bt=1.0).astype(float)
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, 576))
    y[:576] *= ramp
    y[-576:] *= ramp[::-1]
    return y.astype(np.float32)


def q65_audio(message, f0=1500.0):
    """Q65-60A: 85 symbols x 0.6 s (51 s), 1.667 Hz tone spacing, plain continuous-phase FSK.
    f0 is the sync tone, which is the frequency WSJT-X reports for a Q65 signal."""
    return gfsk(q65_tones(message), 7200, FS / 7200, f0).astype(np.float32)


def wspr_audio(call, grid, dbm, f0=1500.0):
    """162 symbols x 8192/12000 s, 1.4648 Hz spacing (110.6 s). f0 = centre of signal."""
    spacing = FS / 8192
    return gfsk(wspr_tones(call, grid, dbm), 8192, spacing, f0 - 1.5 * spacing)


# --------------------------------------------------------------------------- receive: WSJT-X decoders
# jt9 (FT8) and wsprd (WSPR) are WSJT-X's own decoders. Uranus records one slot of the
# radio's audio at 12 kHz, writes it to a WAV and runs the decoder on it, exactly as
# WSJT-X does internally, then reads the decoded lines.

_FT8_LINE = re.compile(r"^\s*(\d{4,6})\s+(-?\d+)\s+(-?\d+\.\d)\s+(\d+)\s+[~#:@+&$]\s+(.+?)\s*$")
_WSPR_LINE = re.compile(r"(-?\d+)\s+(-?\d+\.\d+)\s+(\d+\.\d{6})\s+(-?\d+)\s+(\S.*?)\s*$")
_FLAGS = re.compile(r"\s+q\d\s*$|\s{2,}(\?\s*)?(a\d)?\s*$|\s+\?\s*(a\d)?\s*$|\s+a\d\s*$")
_GRID = re.compile(r"^[A-R]{2}\d{2}([A-Xa-x]{2})?$")
_CALL = re.compile(r"^(?=.*\d)[A-Z0-9/]{3,11}$")


class DecoderMissing(RuntimeError):
    pass


def decoder_path(tool):
    exe = _find(tool)
    if not exe:
        raise DecoderMissing(f"{tool} not found. FT8 and WSPR decoding use WSJT-X's own decoders: install "
                             "WSJT-X (free, from wsjt.sourceforge.io). Uranus finds it in C:\\WSJT\\wsjtx\\bin, "
                             "or set WSJTX_BIN to its bin folder.")
    return exe


def _write_wav(path, x, fs=FS):
    import wave
    pcm = (np.clip(np.asarray(x, float) / (np.max(np.abs(x)) + 1e-9) * 0.7, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


def parse_ft8_message(msg):
    """(sender, grid) from an FT8 message text. Grid is '' when the message has none."""
    t = msg.replace("<", "").replace(">", "").split()
    if not t:
        return None, ""
    if t[0] == "CQ":
        rest = t[1:]
        if rest and not _CALL.match(rest[0]) and len(rest) > 1:
            rest = rest[1:]                  # CQ DX / CQ POTA ...
        call = rest[0] if rest else None
        grid = rest[1] if len(rest) > 1 and _GRID.match(rest[1]) and rest[1] != "RR73" else ""
        return (call if call and _CALL.match(call) else None), grid
    if len(t) >= 2 and _CALL.match(t[1]):
        grid = t[2] if len(t) > 2 and _GRID.match(t[2]) and t[2] != "RR73" else ""
        return t[1], grid
    return None, ""


def ft8_decode(x, dial_hz, fs=FS, workdir=None):
    """Decode one 15-second FT8 slot with WSJT-X's jt9. Returns dicts: snr, dt, freq_hz, message, call, grid."""
    return _jt9_decode(x, dial_hz, "-8", "15", 15.0, fs, workdir)


def ft4_decode(x, dial_hz, fs=FS, workdir=None):
    """Decode one 7.5-second FT4 slot with WSJT-X's jt9 (FT4 mode)."""
    return _jt9_decode(x, dial_hz, "-5", "7", 7.5, fs, workdir)


# Deep decode: jt9 already runs at its deepest setting (-d 3). Giving it our own callsign and grid also turns on
# WSJT-X's a priori decoding, which recovers weaker replies addressed to us. Set by the listener from the settings.
_STATION = {"call": "", "grid": ""}


def set_station(call, grid):
    """Tell jt9 our callsign and 4-character grid for a priori (callsign-aware) decoding."""
    call = (call or "").strip().upper().split("-")[0]          # APRS SSID (8P5AB-10) -> 8P5AB
    grid = (grid or "").strip()[:4].upper()
    ok_call = bool(_CALL.match(call)) and call != "N0CALL"
    _STATION.update(call=call if ok_call else "", grid=grid if ok_call and _GRID.match(grid) else "")


def _station_args():
    a = []
    if _STATION["call"]:
        a += ["-c", _STATION["call"]]
        if _STATION["grid"]:
            a += ["-G", _STATION["grid"]]
    return a


def q65_decode(x, dial_hz, fs=FS, workdir=None):
    """Decode one 60-second Q65-60A slot with WSJT-X's jt9. About 6 to 7 dB deeper than FT8, made for weak and
    fading VHF paths (tropo scatter, rain scatter, EME). Returns the same dicts as ft8_decode."""
    return _jt9_decode(x, dial_hz, "-3", "60", 60.0, fs, workdir, extra=("-b", "A"))


def _jt9_decode(x, dial_hz, flag, period, seconds, fs=FS, workdir=None, extra=()):
    import tempfile
    exe = decoder_path("jt9")
    n = int(seconds * fs)
    x = np.asarray(x, float)
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    d = workdir or tempfile.mkdtemp(prefix="uranus_jt9_")
    wav = os.path.join(d, "000000_000000.wav")
    _write_wav(wav, x, fs)
    out = subprocess.run([exe, flag, "-p", period, "-d", "3", "-L", "100", "-H", "3200", *extra, *_station_args(),
                          "-a", d, "-t", d, wav], capture_output=True, text=True, timeout=60, cwd=d, **_HIDE).stdout
    res = []
    for line in out.splitlines():
        m = _FT8_LINE.match(line)
        if not m:
            continue
        msg = m.group(5).strip()
        flags = ""
        fm = _FLAGS.search(msg)
        if fm:                                   # WSJT-X quality / a-priori markers, e.g. "? a1"
            flags, msg = fm.group(0).strip(), msg[:fm.start()].rstrip()
        call, grid = parse_ft8_message(msg)
        res.append({"snr": float(m.group(2)), "dt": float(m.group(3)), "freq_hz": int(dial_hz + int(m.group(4))),
                    "message": msg, "call": call, "grid": grid, "flags": flags})
    return res


def wspr_decode(x, dial_hz, fs=FS, workdir=None, utc=None):
    """Decode one 2-minute WSPR slot with WSJT-X's wsprd. Returns dicts: snr, dt, freq_hz, drift, call, grid, dbm."""
    import tempfile
    import time
    exe = decoder_path("wsprd")
    n = 114 * fs
    x = np.asarray(x, float)
    x = np.pad(x, (0, max(0, n - len(x))))[:n]
    d = workdir or tempfile.mkdtemp(prefix="uranus_wspr_")
    stamp = time.strftime("%y%m%d_%H%M", time.gmtime(utc or time.time()))
    wav = os.path.join(d, stamp + ".wav")
    _write_wav(wav, x, fs)
    out = subprocess.run([exe, "-f", f"{dial_hz / 1e6:.6f}", "-a", d, wav], capture_output=True, text=True,
                         timeout=120, cwd=d, **_HIDE).stdout
    res = []
    for line in out.splitlines():
        if "<DecodeFinished>" in line:
            continue
        m = _WSPR_LINE.search(line)
        if not m:
            continue
        t = m.group(5).replace("<", "").replace(">", "").split()
        call = t[0] if t and _CALL.match(t[0]) else None
        grid = t[1] if len(t) > 1 and _GRID.match(t[1]) else ""
        dbm = int(t[-1]) if t and t[-1].lstrip("-").isdigit() else None
        res.append({"snr": float(m.group(1)), "dt": float(m.group(2)), "freq_hz": int(float(m.group(3)) * 1e6),
                    "drift": int(m.group(4)), "message": " ".join(t), "call": call, "grid": grid, "dbm": dbm})
    return res
