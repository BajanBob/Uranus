"""APRS: AX.25 UI frames as Bell-202 AFSK (1200 baud, 1200/2200 Hz) audio.

Feed the audio to an FM transmitter (rig in FM mode, data/mic input).
"""

import numpy as np

FS = 48000
BAUD = 1200
MARK, SPACE = 1200.0, 2200.0


def crc_x25(data: bytes) -> int:
    """CRC-16/X.25 - the AX.25 frame check sequence. crc_x25(b'123456789') == 0x906E."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _addr(callsign: str, last: bool) -> bytes:
    call, _, ssid = callsign.upper().partition("-")
    if not (1 <= len(call) <= 6 and call.isalnum()):
        raise ValueError(f"bad AX.25 callsign {callsign!r}")
    ssid = int(ssid or 0)
    if not 0 <= ssid <= 15:
        raise ValueError("SSID must be 0-15")
    return bytes(ord(c) << 1 for c in call.ljust(6)) + bytes([0x60 | (ssid << 1) | int(last)])


def build_frame(source, info, dest="APZURA", path=("WIDE1-1", "WIDE2-1")) -> bytes:
    """AX.25 UI frame including FCS. APZ* is the experimental-software tocall."""
    calls = [dest, source] + list(path)
    addr = b"".join(_addr(c, i == len(calls) - 1) for i, c in enumerate(calls))
    body = addr + b"\x03\xf0" + info.encode("ascii")
    fcs = crc_x25(body)
    return body + bytes([fcs & 0xFF, fcs >> 8])


def position_info(lat, lon, symbol_table="/", symbol="-", comment=""):
    """Uncompressed APRS position, no timestamp, no messaging ('!')."""
    ns, ew = ("N" if lat >= 0 else "S"), ("E" if lon >= 0 else "W")
    lat, lon = abs(lat), abs(lon)
    la = f"{int(lat):02d}{(lat - int(lat)) * 60:05.2f}{ns}"
    lo = f"{int(lon):03d}{(lon - int(lon)) * 60:05.2f}{ew}"
    return f"!{la}{symbol_table}{lo}{symbol}{comment}"[:80]


def hdlc_bits(frame: bytes, preamble_flags=40, tail_flags=4):
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    bits = flag * preamble_flags
    ones = 0
    for byte in frame:
        for i in range(8):                   # LSB first
            b = (byte >> i) & 1
            bits.append(b)
            if b:
                ones += 1
                if ones == 5:
                    bits.append(0)           # bit stuffing
                    ones = 0
            else:
                ones = 0
    return bits + flag * tail_flags


def afsk(bits, fs=FS, amp=0.5):
    """NRZI (0 = change tone) + continuous-phase AFSK."""
    spb = fs / BAUD
    tone, freqs = MARK, []
    for b in bits:
        if b == 0:
            tone = SPACE if tone == MARK else MARK
        freqs.append(tone)
    n = int(round(len(bits) * spb))
    f = np.asarray(freqs)[(np.arange(n) / spb).astype(int).clip(0, len(freqs) - 1)]
    return (amp * np.sin(2 * np.pi * np.cumsum(f) / fs)).astype(np.float32)


def packet_audio(source, info, path=("WIDE1-1", "WIDE2-1"), txdelay_ms=300, fs=FS):
    flags = max(1, int(txdelay_ms / 1000 * BAUD / 8))
    return afsk(hdlc_bits(build_frame(source, info, path=path), preamble_flags=flags), fs)


# --------------------------------------------------------------------------- self-check demod
def demod_check(audio, fs=FS):
    """Minimal aligned demodulator used by the tests (not a field receiver)."""
    spb = fs / BAUD
    nb = int(len(audio) / spb)
    t = np.arange(int(spb)) / fs
    cm, sm = np.exp(-2j * np.pi * MARK * t), np.exp(-2j * np.pi * SPACE * t)
    tones = []
    for i in range(nb):
        seg = audio[int(i * spb):int(i * spb) + len(t)]
        tones.append(abs(seg @ cm[:len(seg)]) > abs(seg @ sm[:len(seg)]))
    bits = [1] + [int(tones[i] == tones[i - 1]) for i in range(1, nb)]
    s = "".join(map(str, bits))
    frames = [p for p in s.split("01111110") if len(p) > 100]
    out = []
    for p in frames:
        raw, ones = [], 0
        for ch in p:
            if ones == 5:
                ones = 0
                continue                     # stuffed zero
            raw.append(int(ch))
            ones = ones + 1 if ch == "1" else 0
        data = bytes(sum(raw[i + k] << k for k in range(8)) for i in range(0, len(raw) - 7, 8))
        if len(data) > 18 and crc_x25(data[:-2]) == data[-2] | (data[-1] << 8):
            out.append(data[:-2])
    return out
