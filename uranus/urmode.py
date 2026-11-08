"""UR mode - Uranus experimental weak-signal beacon modulation.

Frame (all submodes share it, only the symbol length changes):

    payload 64 bits  = callsign 32 + grid 15 + msg-type 3 + value 14
    + CRC-16          -> 80 bits
    + K=9 r=1/3 conv  -> (80+8)*3 = 264 coded bits
    interleaver       -> position i carries coded bit (97*i mod 264)
    Gray 4-FSK        -> 132 data symbols
    + 4 x 8 sync      -> 164 channel symbols:  S D44 S D44 S D44 S

Submodes (symbol length T, tone spacing 1/T, 4 tones):

    UR-15  T=0.08 s  13.1 s on air  12.5  Hz spacing  50  Hz wide
    UR-30  T=0.16 s  26.2 s          6.25 Hz           25  Hz
    UR-60  T=0.32 s  52.5 s          3.125 Hz          12.5 Hz
    UR-120 T=0.64 s 105.0 s          1.5625 Hz          6.3 Hz
    UR-300 T=1.60 s 262.4 s          0.625 Hz           2.5 Hz

Receiver features that buy sensitivity (all measured by `ur-sim`):
  * soft-decision noncoherent LLRs into a soft Viterbi decoder
  * a-priori decoding: known callsign/grid bits are forced in the trellis
  * LLR stacking: identical repeats, or the same frame heard by several
    receivers, are summed before decoding (+3 dB per doubling, ideal)
"""

import numpy as np
from scipy.special import i0e

from .fec import (bits_to_int, conv_encode, crc16, int_to_bits, viterbi_decode)

FS = 12000
SUBMODES = {"UR-15": 0.08, "UR-30": 0.16, "UR-60": 0.32, "UR-120": 0.64, "UR-300": 1.6}
PERIODS = {"UR-15": 15, "UR-30": 30, "UR-60": 60, "UR-120": 120, "UR-300": 300}

NPAYLOAD, NCRC = 64, 16
NINFO = NPAYLOAD + NCRC                 # 80
NCODED = (NINFO + 8) * 3                # 264
NDATA = NCODED // 2                     # 132
SYNC = np.array([0, 1, 3, 2, 1, 0, 2, 3])
NSYM = NDATA + 4 * len(SYNC)            # 164
PERM = (np.arange(NCODED) * 97) % NCODED

GRAY = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3}
TONE_BITS = {v: k for k, v in GRAY.items()}

# Channel-symbol layout
_layout = []
for blk in range(4):
    _layout += [("s", i) for i in range(8)]
    if blk < 3:
        _layout += [("d", blk * 44 + i) for i in range(44)]
SYNC_POS = np.array([n for n, (k, _) in enumerate(_layout) if k == "s"])
SYNC_TONES = np.tile(SYNC, 4)
DATA_POS = np.array([n for n, (k, _) in enumerate(_layout) if k == "d"])

CHARS = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


# --------------------------------------------------------------------------- message
def pack_message(call, grid, mtype=0, value=0):
    call = call.strip().upper()
    grid = grid.strip().upper()
    if not (1 <= len(call) <= 6 and all(c in CHARS[1:] for c in call)):
        raise ValueError("callsign: 1-6 letters/digits")
    if len(grid) != 4 or not ("A" <= grid[0] <= "R" and "A" <= grid[1] <= "R"
                              and grid[2:].isdigit()):
        raise ValueError("grid: 4 characters like GK03")
    if not (0 <= mtype < 8 and 0 <= value < 16384):
        raise ValueError("type 0-7, value 0-16383")
    n = 0
    for c in call.ljust(6):
        n = n * 37 + CHARS.index(c)
    g = ((ord(grid[0]) - 65) * 18 + (ord(grid[1]) - 65)) * 100 + int(grid[2:])
    bits = int_to_bits(n, 32) + int_to_bits(g, 15) + int_to_bits(mtype, 3) + int_to_bits(value, 14)
    return bits + int_to_bits(crc16(bits), 16)


def unpack_message(bits):
    payload, crc = list(bits[:NPAYLOAD]), bits_to_int(bits[NPAYLOAD:NINFO])
    if crc16(payload) != crc:
        return None
    n = bits_to_int(payload[:32])
    chars = []
    for _ in range(6):
        n, r = divmod(n, 37)
        chars.append(CHARS[r])
    call = "".join(reversed(chars)).strip()
    g = bits_to_int(payload[32:47])
    if n or g >= 32400 or not call:
        return None
    gl, gd = divmod(g, 100)
    grid = chr(65 + gl // 18) + chr(65 + gl % 18) + f"{gd:02d}"
    return {"call": call, "grid": grid, "type": bits_to_int(payload[47:50]),
            "value": bits_to_int(payload[50:64])}


def known_bits(call=None, grid=None):
    """A-priori mask for viterbi_decode: -1 = unknown."""
    k = [-1] * NINFO
    ref = pack_message(call or "A", grid or "AA00")
    if call:
        k[0:32] = ref[0:32]
    if grid:
        k[32:47] = ref[32:47]
    return k


# --------------------------------------------------------------------------- encoder
def message_to_tones(call, grid, mtype=0, value=0):
    coded = conv_encode(pack_message(call, grid, mtype, value))
    tx = coded[PERM]
    data = [GRAY[(int(tx[2 * i]), int(tx[2 * i + 1]))] for i in range(NDATA)]
    tones = np.zeros(NSYM, dtype=int)
    tones[SYNC_POS] = SYNC_TONES
    tones[DATA_POS] = data
    return tones


def modulate(tones, submode="UR-60", f0=1500.0, amp=0.5, fs=FS, bt=1.0):
    """Continuous-phase 4-GFSK audio. f0 is the centre of the 4-tone group."""
    T = SUBMODES[submode]
    nsps = int(round(T * fs))
    spacing = 1.0 / T
    freq = np.repeat((np.asarray(tones) - 1.5) * spacing, nsps).astype(float)
    if bt:
        sigma = nsps * np.sqrt(np.log(2)) / (2 * np.pi * bt)
        x = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
        g = np.exp(-0.5 * (x / sigma) ** 2)
        freq = np.convolve(np.pad(freq, len(x) // 2, mode="edge"), g / g.sum(), mode="valid")
    phase = 2 * np.pi * np.cumsum(f0 + freq) / fs
    y = amp * np.sin(phase)
    ramp = min(nsps // 8, 240)
    w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
    y[:ramp] *= w
    y[-ramp:] *= w[::-1]
    return y.astype(np.float32)


# --------------------------------------------------------------------------- decoder core
def _log_i0(x):
    return np.log(i0e(x)) + x


def tone_llrs(Y, amp, n0):
    """Y: (NSYM,4) complex matched-filter outputs. Returns coded-bit LLRs (de-interleaved)."""
    L = _log_i0(2.0 * amp * np.abs(Y[DATA_POS]) / n0)          # (132,4)
    la = np.logaddexp
    b1 = la(L[:, 0], L[:, 1]) - la(L[:, 2], L[:, 3])           # first bit of pair
    b0 = la(L[:, 0], L[:, 3]) - la(L[:, 1], L[:, 2])           # second bit
    tx = np.empty(NCODED)
    tx[0::2], tx[1::2] = b1, b0
    llr = np.empty(NCODED)
    llr[PERM] = tx
    return llr


def decode_llr(llr, known=None):
    bits = viterbi_decode(llr, NINFO, known)
    return unpack_message(bits)


# --------------------------------------------------------------------------- WAV decoder
def decode_audio(x, submode="UR-60", fs=FS, fmin=300.0, fmax=2700.0, max_dt=4.0,
                 ncand=12, known=None, return_llr=False):
    """Search time/frequency, then decode. Returns list of decode dicts."""
    T = SUBMODES[submode]
    N = int(round(T * fs))
    hop, os_f = N // 4, 4
    nfft = N * os_f
    x = np.asarray(x, dtype=float)
    need = NSYM * N
    nframes = (len(x) - N) // hop + 1
    if nframes < 4 * (NSYM - 1) + 1:
        return []
    frames = np.lib.stride_tricks.sliding_window_view(x, N)[::hop][:nframes]
    X = np.fft.rfft(frames, nfft, axis=1)
    P = np.abs(X) ** 2
    df = fs / nfft
    b_lo, b_hi = int(fmin / df), int(fmax / df) - 3 * os_f
    nt = min(nframes - 4 * (NSYM - 1), int(max_dt * fs / hop) + 1)
    if nt <= 0 or b_hi <= b_lo:
        return []
    bs = np.arange(b_lo, b_hi)
    num = np.zeros((nt, len(bs)))
    den = np.zeros((nt, len(bs)))
    for pos, tone in zip(SYNC_POS, SYNC_TONES):
        rows = P[np.arange(nt) + 4 * pos]
        num += rows[:, bs + os_f * tone]
        den += sum(rows[:, bs + os_f * k] for k in range(4))
    metric = num / (den + 1e-30)
    n0 = np.median(P[:, b_lo:b_hi + 3 * os_f]) / np.log(2)

    results, tried = [], []
    order = np.argsort(metric, axis=None)[::-1]
    for idx in order:
        if len(tried) >= ncand:
            break
        t0, bi = np.unravel_index(idx, metric.shape)
        b = bs[bi]
        if any(abs(t0 - a) < 4 and abs(b - c) < 2 * os_f for a, c in tried):
            continue
        tried.append((t0, b))
        rows = X[t0 + 4 * np.arange(NSYM)]
        Y = np.stack([rows[:, b + os_f * k] for k in range(4)], axis=1)
        sig = np.abs(Y[SYNC_POS, SYNC_TONES]) ** 2
        a2 = max(np.mean(sig) - n0, 0.05 * n0)
        llr = tone_llrs(Y, np.sqrt(a2), n0)
        if return_llr:
            results.append({"llr": llr, "t0": t0 * hop / fs, "f0": (b + 1.5 * os_f) * df})
            continue
        msg = decode_llr(llr, known)
        if msg and not any(r["call"] == msg["call"] and r["value"] == msg["value"] for r in results):
            snr = 10 * np.log10(a2 / (2500 * T * n0) * (1.0))
            msg.update(dt=round(t0 * hop / fs, 2), freq=round((b + 1.5 * os_f) * df, 1),
                       snr=round(float(snr), 1))
            results.append(msg)
    return results


# --------------------------------------------------------------------------- simulation
def awgn_tone_outputs(tones, esn0_db, rng):
    """Ideal-sync matched-filter outputs for noncoherent orthogonal 4-FSK, N0 = 1."""
    a = np.sqrt(10 ** (esn0_db / 10))
    Y = (rng.standard_normal((NSYM, 4)) + 1j * rng.standard_normal((NSYM, 4))) / np.sqrt(2)
    Y[np.arange(NSYM), tones] += a * np.exp(2j * np.pi * rng.random(NSYM))
    return Y, a


def snr2500_from_esn0(esn0_db, submode):
    return esn0_db - 10 * np.log10(2500 * SUBMODES[submode])


def esn0_from_snr2500(snr_db, submode):
    return snr_db + 10 * np.log10(2500 * SUBMODES[submode])
