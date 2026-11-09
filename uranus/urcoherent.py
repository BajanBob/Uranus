"""URC - coherent UR mode with pilot-aided carrier recovery.

Same 64-bit payload, CRC-16 and K=9 r=1/3 code as UR, but:

    264 coded bits -> +/-1 symbols b_k
    one known pilot symbol after every 4 data symbols -> 330 symbols
    pilots follow a PRBS7 +/-1 sequence (gives clean timing correlation)
    MSK on air: baseband = sum b_k * j^k * halfsine(t - kT), pulse length 2T.
      This is constant-envelope (0 dB peak-to-average, like FST4 and like
      a phase-modulated carrier), so a rig runs it at full power,
      yet each symbol detects coherently with BPSK performance.

Receiver ("carrier recovery of a signal buried in noise"):
  1. Mix down at the nominal audio frequency, matched-filter (RRC).
  2. Joint timing / frequency search: for every timing candidate, an FFT of
     the pilot-wiped samples finds the frequency offset (a fine Doppler grid).
  3. A complex-domain Kalman filter + Rauch-Tung-Striebel smoother tracks the
     carrier phasor between pilots. This is the "predictive" part: the
     random-walk model predicts where the phase is going, and the backward
     pass uses future pilots too. Working on the complex phasor avoids phase
     wrapping at very low SNR.
  4. Coherent LLRs -> soft Viterbi (with optional a-priori bits) -> CRC.

Requires stable oscillators at both ends (GPSDO or very good TCXO): the
frequency search covers +/- df_max Hz around the nominal audio frequency.
"""

import numpy as np
from scipy.signal import fftconvolve

from . import urmode
from .fec import conv_encode, viterbi_decode

FS = 12000
SUBMODES = {"URC-15": 0.04, "URC-30": 0.08, "URC-60": 0.16, "URC-120": 0.32, "URC-300": 0.8}
PERIODS = {k: int(k.split("-")[1]) for k in SUBMODES}
BETA = 0.5
NCODED = urmode.NCODED                 # 264
NSYM = NCODED + NCODED // 4            # 330
PILOT_POS = np.arange(4, NSYM, 5)      # 66 pilots, after every 4 data symbols
DATA_POS = np.setdiff1d(np.arange(NSYM), PILOT_POS)


def _prbs7(n):
    s, out = 0x7F, []
    for _ in range(n):
        b = ((s >> 6) ^ (s >> 5)) & 1
        s = ((s << 1) | b) & 0x7F
        out.append(1.0 - 2.0 * b)
    return np.array(out)


PILOTS = _prbs7(len(PILOT_POS))
DEROT = (-1j) ** np.arange(NSYM)               # undo the MSK j^k rotation


def rrc(sps, beta=BETA, span=8):
    t = np.arange(-span * sps, span * sps + 1) / sps
    h = np.zeros_like(t)
    for i, x in enumerate(t):
        if x == 0:
            h[i] = 1 - beta + 4 * beta / np.pi
        elif abs(abs(4 * beta * x) - 1) < 1e-9:
            h[i] = beta / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                        + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * x * (1 - beta)) + 4 * beta * x * np.cos(np.pi * x * (1 + beta))) \
                   / (np.pi * x * (1 - (4 * beta * x) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


def message_to_symbols(call, grid, mtype=0, value=0):
    coded = conv_encode(urmode.pack_message(call, grid, mtype, value))
    tx = coded[urmode.PERM]
    s = np.empty(NSYM)
    s[DATA_POS] = 1.0 - 2.0 * tx
    s[PILOT_POS] = PILOTS
    return s


def halfsine(sps):
    p = np.sin(np.pi * (np.arange(2 * sps) + 0.5) / (2 * sps))
    return p / np.sqrt(np.sum(p ** 2))


def modulate(symbols, submode="URC-60", f0=1500.0, amp=0.5, fs=FS):
    """Constant-envelope MSK audio (upper-sideband baseband shifted to f0)."""
    sps = int(round(SUBMODES[submode] * fs))
    rot = np.asarray(symbols) * (1j ** np.arange(len(symbols)))
    up = np.zeros(len(symbols) * sps + sps, complex)
    up[:len(symbols) * sps:sps] = rot
    bb = fftconvolve(up, halfsine(sps))[:len(up)]
    t = np.arange(len(bb)) / fs
    y = np.real(bb * np.exp(2j * np.pi * f0 * t))
    peak = np.max(np.abs(bb))
    y = amp * y / peak
    r = min(sps // 2, 240)                      # gentle on/off ramps
    w = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, r))
    y[:r] *= w
    y[-r:] *= w[::-1]
    return y.astype(np.float32)


# --------------------------------------------------------------------------- receiver core
def rts_phasor(z_pilot, r_ratio):
    """Complex random-walk Kalman filter + RTS smoother.

    z_pilot : pilot observations h_p + noise (pilot already wiped)
    r_ratio : process variance / measurement variance per pilot interval
    returns smoothed phasor estimates at the pilots.
    """
    n = len(z_pilot)
    R, Q = 1.0, r_ratio
    xf, Pf, xp, Pp = (np.zeros(n, complex), np.zeros(n), np.zeros(n, complex), np.zeros(n))
    x, P = z_pilot[0], R
    for k in range(n):
        if k:
            x, P = x, P + Q                        # predict
        xp[k], Pp[k] = x, P
        K = P / (P + R)                            # update
        x = x + K * (z_pilot[k] - x)
        P = (1 - K) * P
        xf[k], Pf[k] = x, P
    xs = xf.copy()
    for k in range(n - 2, -1, -1):
        G = Pf[k] / Pp[k + 1]
        xs[k] = xf[k] + G * (xs[k + 1] - xp[k + 1])
    return xs


def symbols_to_llr(r, df_max_cycles=0.0, phase_walk=0.02, nfft=4096, genie_h=None):
    """r: 330 complex matched-filter samples (any amplitude). Returns (llr, freq_offset_cyc/sym)."""
    zp = r[PILOT_POS] * PILOTS
    if genie_h is not None:
        h = genie_h
        n0 = 1.0
        fo = 0.0
    else:
        fo = 0.0
        if df_max_cycles > 0:                      # frequency search over pilots
            spec = np.fft.fft(zp, nfft)
            f = np.fft.fftfreq(nfft, d=5.0)        # cycles/symbol (pilot spacing 5)
            ok = np.abs(f) <= df_max_cycles
            fo = f[ok][np.argmax(np.abs(spec[ok]))]
        k = np.arange(NSYM)
        r = r * np.exp(-2j * np.pi * fo * k)
        zp = r[PILOT_POS] * PILOTS
        n_tot = np.mean(np.abs(r) ** 2)
        a2 = max(np.abs(np.mean(zp)) ** 2, 1e-3 * n_tot)
        n0 = max(n_tot - a2, 1e-9)
        hp = rts_phasor(zp, phase_walk * max(a2, 1e-9) / n0)
        h = np.interp(k, PILOT_POS, hp.real) + 1j * np.interp(k, PILOT_POS, hp.imag)
    llr_tx = 4.0 * np.real(r[DATA_POS] * np.conj(h[DATA_POS])) / n0
    llr = np.empty(NCODED)
    llr[urmode.PERM] = llr_tx
    return llr, fo


def decode_llr(llr, known=None):
    return urmode.unpack_message(viterbi_decode(llr, urmode.NINFO, known))


# --------------------------------------------------------------------------- audio decoder
def decode_audio(x, submode="URC-60", fs=FS, f_nom=1500.0, df_max=5.0, max_dt=4.0,
                 phase_walk=0.02, known=None, ncand=6):
    T = SUBMODES[submode]
    sps = int(round(T * fs))
    x = np.asarray(x, float)
    t = np.arange(len(x)) / fs
    p = halfsine(sps)
    mf = fftconvolve(x * np.exp(-2j * np.pi * f_nom * t), p[::-1])
    bb = mf[len(p) - 1:]                        # bb[n] = output for a pulse starting at n
    span = (NSYM - 1) * sps
    step = max(1, sps // 8)
    taus = np.arange(0, min(int(max_dt * fs), len(bb) - span - 1), step)
    if len(taus) == 0:
        return []
    nfft = 2048
    fgrid = np.fft.fftfreq(nfft, d=5 * T)          # Hz
    ok = np.abs(fgrid) <= df_max
    scores = []
    for tau in taus:
        zp = bb[tau + PILOT_POS * sps] * DEROT[PILOT_POS] * PILOTS
        spec = np.abs(np.fft.fft(zp, nfft))[ok]
        scores.append(spec.max())
    scores = np.array(scores)
    out, tried = [], []
    for i in np.argsort(scores)[::-1]:
        if len(tried) >= ncand:
            break
        tau = taus[i]
        if any(abs(tau - a) < sps for a in tried):
            continue
        tried.append(tau)
        r = bb[tau + np.arange(NSYM) * sps] * DEROT
        llr, fo = symbols_to_llr(r, df_max * T, phase_walk)
        m = decode_llr(llr, known)
        if m:
            zp = r * np.exp(-2j * np.pi * fo * np.arange(NSYM))
            a2 = np.abs(np.mean(zp[PILOT_POS] * PILOTS)) ** 2
            n0 = max(np.mean(np.abs(zp) ** 2) - a2, 1e-12)
            m.update(dt=round(tau / fs, 2), df=round(fo / T, 3),
                     snr=round(float(10 * np.log10(a2 / n0 / (2500 * T))), 1))
            out.append(m)
            break
    return out


# --------------------------------------------------------------------------- simulation
def channel(symbols, esn0_db, rng, df_cyc=0.0, walk_rad=0.0):
    """Symbol-level channel: carrier offset (cycles/symbol), phase random walk, AWGN (N0=1)."""
    a = np.sqrt(10 ** (esn0_db / 10))
    k = np.arange(NSYM)
    ph = 2 * np.pi * rng.random() + 2 * np.pi * df_cyc * k + np.cumsum(walk_rad * rng.standard_normal(NSYM))
    h = a * np.exp(1j * ph)
    n = (rng.standard_normal(NSYM) + 1j * rng.standard_normal(NSYM)) / np.sqrt(2)
    return h * symbols + n, h


def snr2500_from_esn0(esn0_db, submode):
    return esn0_db - 10 * np.log10(2500 * SUBMODES[submode])
