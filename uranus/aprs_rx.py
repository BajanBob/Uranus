"""APRS receiver: Bell-202 AFSK (1200 baud) audio to AX.25 frames to stations and positions.

Works on the receiver's FM audio (FM-D, squelch open). Several decoders run side by
side on every block: with and without compensation for FM de-emphasis (which makes
the 1200 Hz tone louder than 2200 Hz), each at several bit-clock phases. A frame
counts only if its CRC-16 (X.25) checks, so false decodes are very rare.

Positions understood: plain (!, =, /, @), compressed, and Mic-E.
"""

import numpy as np

from . import aprs

BAUD = 1200


def _bandpass(x, fs, lo=900, hi=2500):
    try:
        from scipy.signal import butter, sosfiltfilt
        sos = butter(4, [lo, hi], btype="band", fs=fs, output="sos")
        return sosfiltfilt(sos, x)
    except Exception:                            # noqa: BLE001
        return x - np.mean(x)


def _tone_energy(x, f, fs, n):
    t = np.arange(len(x)) / fs
    z = x * np.exp(-2j * np.pi * f * t)
    k = np.ones(n) / n
    return np.abs(np.convolve(z, k, mode="same"))


def _smooth(v, n):
    return np.convolve(v, np.ones(n) / n, mode="same") + 1e-9


def demod_bits(x, fs, baud=BAUD, mark=aprs.MARK, space=aprs.SPACE):
    """Yield candidate bit streams (lists of 0/1, NRZI-decoded) from one audio block."""
    lo, hi = min(mark, space), max(mark, space)
    x = _bandpass(np.asarray(x, dtype=float), fs, max(100, lo - 300), hi + 300)
    spb = fs / baud
    n = max(2, int(round(spb)))
    m = _tone_energy(x, mark, fs, n)
    s = _tone_energy(x, space, fs, n)
    slow = int(spb * 32)
    variants = [m - s, m / _smooth(m, slow) - s / _smooth(s, slow)]   # plain, de-emphasis compensated
    for d in variants:
        for phase in np.linspace(0, spb, 5, endpoint=False):
            idx = (phase + spb / 2 + np.arange(int((len(d) - phase) / spb) - 1) * spb).astype(int)
            idx = idx[idx < len(d)]
            tones = d[idx] > 0
            yield [1] + list((tones[1:] == tones[:-1]).astype(int))


def frames_from_bits(bits):
    """HDLC: split on flags, remove stuffed zeros, check the CRC. Returns AX.25 frames without FCS."""
    s = "".join(map(str, bits))
    out = []
    for p in s.split("01111110"):
        if len(p) < 136:                         # shorter than a minimal UI frame (no digipeaters)
            continue
        raw, ones, bad = [], 0, False
        for ch in p:
            if ones == 5:
                if ch == "1":
                    bad = True                   # 6 ones in a row: abort / noise
                    break
                ones = 0
                continue
            raw.append(1 if ch == "1" else 0)
            ones = ones + 1 if ch == "1" else 0
        if bad or len(raw) % 8:
            continue
        data = bytes(sum(raw[i + k] << k for k in range(8)) for i in range(0, len(raw), 8))
        if len(data) >= 18 and aprs.crc_x25(data[:-2]) == data[-2] | (data[-1] << 8):
            out.append(data[:-2])
    return out


def decode_audio(x, fs, hf=False):
    """All distinct AX.25 frames in an audio block. hf=True: 300 baud, 1600/1800 Hz (HF APRS on USB)."""
    seen, out = set(), []
    params = (aprs.HF_BAUD, aprs.HF_MARK, aprs.HF_SPACE) if hf else (BAUD, aprs.MARK, aprs.SPACE)
    for bits in demod_bits(x, fs, *params):
        for fr in frames_from_bits(bits):
            if fr not in seen:
                seen.add(fr)
                out.append(fr)
    return out


# --------------------------------------------------------------------------- AX.25 / APRS parsing
def _call(b):
    call = "".join(chr(c >> 1) for c in b[:6]).strip()
    ssid = (b[6] >> 1) & 0x0F
    return f"{call}-{ssid}" if ssid else call


def parse_frame(fr):
    """dict(source, dest, path, info) or None."""
    addrs, i = [], 0
    while i + 7 <= len(fr):
        addrs.append(fr[i:i + 7])
        i += 7
        if addrs[-1][6] & 1:
            break
    if len(addrs) < 2 or i + 2 > len(fr) or fr[i] != 0x03 or fr[i + 1] != 0xF0:
        return None
    return {"dest": _call(addrs[0]), "source": _call(addrs[1]), "path": [_call(a) for a in addrs[2:]],
            "dest_raw": addrs[0], "info": fr[i + 2:].decode("latin-1", "replace")}


def _plain_pos(s):
    """'ddmm.mmN/dddmm.mmW' at the start of s -> (lat, lon) or None."""
    try:
        lat = int(s[0:2]) + float(s[2:7].replace(" ", "0")) / 60
        lat = -lat if s[7] in "Ss" else lat
        lon = int(s[9:12]) + float(s[12:17].replace(" ", "0")) / 60
        lon = -lon if s[17] in "Ww" else lon
        if s[7] in "NnSs" and s[17] in "EeWw" and abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
    except (ValueError, IndexError):
        pass
    return None


def _b91(s):
    v = 0
    for c in s:
        v = v * 91 + (ord(c) - 33)
    return v


def _compressed_pos(s):
    """'/YYYYXXXX$csT' compressed position -> (lat, lon) or None."""
    try:
        if len(s) < 13 or not all(33 <= ord(c) <= 124 for c in s[1:9]):
            return None
        return 90 - _b91(s[1:5]) / 380926.0, -180 + _b91(s[5:9]) / 190463.0
    except Exception:                            # noqa: BLE001
        return None


def _mic_e(dest_raw, info):
    """Mic-E: latitude in the destination address, longitude in the info field."""
    try:
        d = [chr(c >> 1) for c in dest_raw[:6]]
        digs = []
        for c in d:
            if c.isdigit():
                digs.append(int(c))
            elif "A" <= c <= "J":
                digs.append(ord(c) - ord("A"))
            elif "P" <= c <= "Y":
                digs.append(ord(c) - ord("P"))
            elif c in "KLZ":
                digs.append(0)
            else:
                return None
        lat = digs[0] * 10 + digs[1] + (digs[2] * 10 + digs[3] + (digs[4] * 10 + digs[5]) / 100) / 60
        north = "P" <= d[3] <= "Z"
        lon_off = 100 if "P" <= d[4] <= "Z" else 0
        west = "P" <= d[5] <= "Z"
        b = [ord(c) - 28 for c in info[1:4]]
        deg = b[0] + lon_off
        if 180 <= deg <= 189:
            deg -= 80
        elif 190 <= deg <= 199:
            deg -= 190
        mins = b[1] - 60 if b[1] >= 60 else b[1]
        lon = deg + (mins + b[2] / 100) / 60
        lat, lon = (lat if north else -lat), (-lon if west else lon)
        if abs(lat) <= 90 and abs(lon) <= 180:
            return lat, lon
    except Exception:                            # noqa: BLE001
        pass
    return None


def position(pkt):
    """(lat, lon) from a parsed APRS packet, or None."""
    info = pkt["info"]
    if not info:
        return None
    t = info[0]
    if t in "!=":
        body = info[1:]
    elif t in "/@":
        body = info[8:]                          # 7-character timestamp
    elif t in "`'":
        return _mic_e(pkt["dest_raw"], info)
    else:
        return None
    return _plain_pos(body) or _compressed_pos(body)
