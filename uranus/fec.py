"""Forward error correction used by the UR mode.

* CRC-16/CCITT-FALSE over a bit array (message integrity / false-decode guard)
* Convolutional code K=9, rate 1/3, generators 557, 663, 711 (octal),
  free distance 18 - the same code family used by IS-95 / cdmaOne.
* Soft-decision Viterbi decoder with optional *a-priori* (AP) bits:
  when the receiver already knows some message bits (e.g. the beacon's own
  callsign and grid) those trellis branches are forced, which shrinks the
  number of unknown bits and buys real sensitivity - the same idea WSJT-X
  calls AP decoding.
"""

import numpy as np

K = 9
POLYS = (0o557, 0o663, 0o711)
RATE_INV = len(POLYS)
NSTATES = 1 << (K - 1)
TAIL = K - 1


def _parity(x):
    return bin(x).count("1") & 1


# Output bits for every 9-bit register value (newest bit in LSB).
_OUT = np.array([[_parity(r & g) for g in POLYS] for r in range(1 << K)], dtype=np.int8)
_SIGN = (1 - 2 * _OUT).astype(float)          # +1 for coded 0, -1 for coded 1


def crc16(bits):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over an iterable of 0/1 bits."""
    crc = 0xFFFF
    for b in bits:
        top = (crc >> 15) & 1
        crc = (crc << 1) & 0xFFFF
        if top ^ int(b):
            crc ^= 0x1021
    return crc


def int_to_bits(value, width):
    return [(value >> (width - 1 - i)) & 1 for i in range(width)]


def bits_to_int(bits):
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def conv_encode(bits):
    """Zero-tailed rate-1/3 encoding. Returns (len(bits)+8)*3 coded bits."""
    s, out = 0, []
    for b in list(bits) + [0] * TAIL:
        reg = ((s << 1) | int(b)) & ((1 << K) - 1)
        out.extend(_OUT[reg])
        s = reg & (NSTATES - 1)
    return np.array(out, dtype=np.int8)


_NS = np.arange(NSTATES)
_P0 = _NS >> 1
_P1 = _P0 | (NSTATES >> 1)
_REG0 = _NS
_REG1 = _NS + NSTATES
_INBIT = _NS & 1


def viterbi_decode(llr, nbits, known=None):
    """Soft Viterbi decoding.

    llr   : coded-bit log-likelihood ratios, positive means "bit is 0".
    nbits : number of information bits (tail excluded).
    known : optional sequence of length nbits with 0/1 for known bits and -1
            for unknown (a-priori decoding).
    """
    nsteps = nbits + TAIL
    llr = np.asarray(llr, dtype=float).reshape(nsteps, RATE_INV)
    metric = np.full(NSTATES, -1e18)
    metric[0] = 0.0
    dec = np.zeros((nsteps, NSTATES), dtype=bool)
    for t in range(nsteps):
        bm = _SIGN @ llr[t]
        m0 = metric[_P0] + bm[_REG0]
        m1 = metric[_P1] + bm[_REG1]
        choose = m1 > m0
        metric = np.where(choose, m1, m0)
        dec[t] = choose
        if t >= nbits:                       # tail: input forced to 0
            metric[_INBIT == 1] = -1e18
        elif known is not None and known[t] >= 0:
            metric[_INBIT != known[t]] = -1e18
    s, bits = 0, np.zeros(nsteps, dtype=np.int8)
    for t in range(nsteps - 1, -1, -1):
        bits[t] = s & 1
        s = (s >> 1) | ((NSTATES >> 1) if dec[t, s] else 0)
    return bits[:nbits]
