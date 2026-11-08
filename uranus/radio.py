"""Radio back-ends.

HamlibRadio - any CAT-controlled rig through `rigctld` (Hamlib), audio through
              the rig's USB sound card (`aplay` on Linux; on Windows the
              `sounddevice` package if installed, else the default output
              device via winsound). Recommended hardware: an
              all-mode 2 m / 70 cm rig with USB audio (IC-9700, IC-705, FT-991A...).
              FT8/WSPR/UR need USB (SSB) mode; APRS needs FM.
DryRunRadio - writes each transmission to a WAV and logs it. Nothing is keyed.
"""

import logging
import os
import shutil
import socket
import subprocess
import tempfile
import time
import wave

import numpy as np

log = logging.getLogger("uranus.radio")


def write_wav(path, audio, fs):
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


class DryRunRadio:
    def __init__(self, outdir="out"):
        self.outdir = outdir
        os.makedirs(outdir, exist_ok=True)
        self.n = 0

    def channel_busy(self, seconds, threshold_db):
        return False

    def tune(self, freq_hz, rig_mode):
        log.info("DRY-RUN tune %.4f MHz %s", freq_hz / 1e6, rig_mode)

    def transmit(self, freq_hz, rig_mode, audio, fs, label):
        self.n += 1
        path = os.path.join(self.outdir, f"{self.n:04d}_{label}.wav")
        write_wav(path, audio, fs)
        log.info("DRY-RUN %s on %.4f MHz %s, %.1f s -> %s",
                 label, freq_hz / 1e6, rig_mode, len(audio) / fs, path)


class HamlibRadio:
    def __init__(self, host="127.0.0.1", port=4532, audio_device="default",
                 ptt_lead_s=0.15, max_tx_s=320):
        self.addr = (host, port)
        self.audio_device = audio_device
        self.ptt_lead_s = ptt_lead_s
        self.max_tx_s = max_tx_s
        self.player = _pick_player(audio_device)
        self.sock = socket.create_connection(self.addr, timeout=3)
        self.f = self.sock.makefile("rw")

    def _cmd(self, text):
        self.f.write(text + "\n")
        self.f.flush()
        reply = self.f.readline().strip()
        if reply.startswith("RPRT") and reply != "RPRT 0":
            raise RuntimeError(f"rigctld '{text}' -> {reply}")
        return reply

    def channel_busy(self, seconds, threshold_db):
        """Listen-before-talk: True if the S-meter exceeds threshold_db (dB rel. S9)."""
        end, peak = time.time() + seconds, -999.0
        while time.time() < end:
            try:
                peak = max(peak, float(self._cmd("l STRENGTH")))
            except (ValueError, RuntimeError):
                return False                 # rig can't report: don't block
            time.sleep(0.2)
        return peak > threshold_db

    def transmit(self, freq_hz, rig_mode, audio, fs, label):
        dur = len(audio) / fs
        if dur > self.max_tx_s:
            raise RuntimeError(f"{label}: {dur:.0f} s exceeds max_tx_s")
        tmp = os.path.join(tempfile.gettempdir(), f"uranus_{os.getpid()}.wav")
        write_wav(tmp, audio, fs)
        try:
            self._cmd("T 1")
            time.sleep(self.ptt_lead_s)
            self.player(tmp, audio, fs, dur)
        finally:
            for _ in range(3):               # make very sure PTT drops
                try:
                    self._cmd("T 0")
                    break
                except Exception:            # noqa: BLE001
                    time.sleep(0.2)
            os.unlink(tmp)

    def tune(self, freq_hz, rig_mode):
        self._cmd(f"F {int(freq_hz)}")
        self._cmd(f"M {rig_mode} 0")
        time.sleep(0.3)


def _pick_player(device):
    """Return play(path, audio, fs, dur) for this platform."""
    try:
        import sounddevice as sd             # optional; lets you pick the rig's sound card

        dev = None if device in ("", "default") else (int(device) if str(device).isdigit() else device)

        def play_sd(path, audio, fs, dur):
            sd.play(audio, fs, device=dev, blocking=True)
        return play_sd
    except Exception:                        # noqa: BLE001
        pass
    if os.name == "nt":
        import winsound
        if device not in ("", "default"):
            log.warning("winsound plays to the Windows DEFAULT output device only; "
                        "install 'sounddevice' to choose '%s'", device)

        def play_ws(path, audio, fs, dur):
            winsound.PlaySound(path, winsound.SND_FILENAME)
        return play_ws
    if not shutil.which("aplay"):
        raise RuntimeError("no audio player: install alsa-utils (aplay) or pip install sounddevice")

    def play_aplay(path, audio, fs, dur):
        subprocess.run(["aplay", "-q", "-D", device, path], check=True, timeout=dur + 10)
    return play_aplay
