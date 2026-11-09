"""SDR support.

Receive: RTL-SDR dongle through `rtl_fm` in USB mode, which delivers the same
         12 kHz audio a transceiver would. Used by listen mode when
         [receive] source = "rtl_fm".
Transmit (experimental): HackRF One through `hackrf_transfer`, streaming
         8-bit I/Q from stdin. USB (SSB) for FT8/WSPR/UR/Pumpkin, FM for APRS.
         The carrier is placed `offset_hz` away from the HackRF's centre
         frequency so its DC/LO leak falls outside the wanted signal.

A HackRF puts out only milliwatts and has strong harmonics. On air it MUST
be followed by a band-pass filter for the band in use, and normally an
amplifier with its own filtering. Uranus keeps the gain low by default.
"""

import logging
import shutil
import subprocess
import time

import numpy as np
from scipy.signal import hilbert, resample_poly

log = logging.getLogger("uranus.sdr")


# --------------------------------------------------------------------------- receive
def rtl_record(seconds, dial_hz, ppm=0, gain=40, fs=12000):
    """Record USB audio from an RTL-SDR at `dial_hz` for `seconds`."""
    exe = shutil.which("rtl_fm")
    if not exe:
        raise RuntimeError("rtl_fm not found (Linux/Pi: sudo apt install rtl-sdr)")
    n_bytes = int(seconds * fs) * 2
    cmd = [exe, "-M", "usb", "-f", str(int(dial_hz)), "-s", str(fs), "-p", str(int(ppm)),
           "-g", str(gain), "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        raw = p.stdout.read(n_bytes)
    finally:
        p.terminate()
        p.wait(timeout=5)
    return np.frombuffer(raw, dtype="<i2").astype(float) / 32768


# --------------------------------------------------------------------------- transmit
def iq_chunks(audio, fs_audio, rig_mode, fs_out=2_400_000, offset_hz=200_000, chunk_s=0.5,
              fm_dev_hz=3000.0, scale=110):
    """Yield interleaved int8 I/Q bytes: the audio as USB or FM, shifted by offset_hz."""
    audio = np.asarray(audio, dtype=float)
    up = fs_out // np.gcd(fs_out, fs_audio)
    down = fs_audio // np.gcd(fs_out, fs_audio)
    peak = np.max(np.abs(audio)) or 1.0
    if rig_mode.upper().startswith("FM"):
        phase = 2 * np.pi * fm_dev_hz * np.cumsum(audio / peak) / fs_audio
        base = np.exp(1j * phase)
    else:                                    # USB: analytic signal keeps only the upper sideband
        base = hilbert(audio / peak)
    pad = 64
    step = int(chunk_s * fs_audio)
    n_out_done = 0
    for start in range(0, len(base), step):
        lo, hi = max(0, start - pad), min(len(base), start + step + pad)
        seg = base[lo:hi]
        y = resample_poly(seg.real, up, down) + 1j * resample_poly(seg.imag, up, down)
        a = (start - lo) * up // down
        b = a + (min(start + step, len(base)) - start) * up // down
        y = y[a:b]
        t = (n_out_done + np.arange(len(y))) / fs_out
        y = y * np.exp(2j * np.pi * offset_hz * t)
        n_out_done += len(y)
        iq = np.empty(2 * len(y), dtype=np.int8)
        iq[0::2] = np.clip(np.round(y.real * scale), -127, 127)
        iq[1::2] = np.clip(np.round(y.imag * scale), -127, 127)
        yield iq.tobytes()


class HackRFRadio:
    """Transmit backend: the 'rig' is a HackRF. tune() only remembers the frequency."""

    def __init__(self, txvga=10, amp=False, fs=2_400_000, offset_hz=200_000, max_tx_s=320):
        self.exe = shutil.which("hackrf_transfer")
        if not self.exe:
            raise RuntimeError("hackrf_transfer not found (sudo apt install hackrf)")
        self.txvga, self.amp, self.fs, self.offset, self.max_tx_s = int(txvga), bool(amp), int(fs), int(offset_hz), max_tx_s
        log.warning("HackRF transmit is experimental: use a band-pass filter for the band in use.")

    def channel_busy(self, seconds, threshold_db):
        return False                         # no receiver on this path

    def tune(self, freq_hz, rig_mode):
        pass

    def transmit(self, freq_hz, rig_mode, audio, fs, label):
        dur = len(audio) / fs
        if dur > self.max_tx_s:
            raise RuntimeError(f"{label}: {dur:.0f} s exceeds max_tx_s")
        centre = int(freq_hz - self.offset)
        cmd = [self.exe, "-t", "-", "-f", str(centre), "-s", str(self.fs), "-x", str(self.txvga),
               "-a", "1" if self.amp else "0"]
        log.info("HackRF TX %s: carrier %.6f MHz (centre %.6f), gain %d dB", label, freq_hz / 1e6,
                 centre / 1e6, self.txvga)
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        try:
            for chunk in iq_chunks(audio, fs, rig_mode, self.fs, self.offset):
                p.stdin.write(chunk)
        except BrokenPipeError:
            log.error("hackrf_transfer stopped early (is the HackRF connected?)")
        finally:
            try:
                p.stdin.close()
            except OSError:
                pass
            p.wait(timeout=dur + 15)
        log.info("HackRF TX done in %.1f s", time.time() - t0)
