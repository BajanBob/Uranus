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
import threading
import time
import wave

import numpy as np

log = logging.getLogger("uranus.radio")


class SWRError(RuntimeError):
    """Transmission stopped because the rig reported SWR above the limit."""

    def __init__(self, swr, limit, label=""):
        super().__init__(f"{label}: SWR {swr:.1f} above {limit:.1f} - PTT dropped".lstrip(": "))
        self.swr, self.limit, self.label = swr, limit, label


def _stop_audio():
    """Cut transmit audio short (called from the SWR watchdog thread)."""
    try:
        import sounddevice as sd
        sd.stop()
    except Exception:                        # noqa: BLE001
        pass
    if os.name == "nt":
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except Exception:                    # noqa: BLE001
            pass
    p = _APLAY.get("p")
    if p is not None and p.poll() is None:
        p.kill()


_APLAY = {}


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
                 ptt_lead_s=0.15, max_tx_s=320, data_mode=True, max_swr=2.0):
        self.addr = (host, port)
        self.max_swr = float(max_swr or 0)   # 0 = no SWR check
        self.swr_poll_s = 0.5
        self.last_swr = None                 # highest SWR seen during the last transmission
        self._lock = threading.Lock()
        self._swr_warned = False
        self.data_mode = data_mode
        self.audio_device = audio_device
        self.ptt_lead_s = ptt_lead_s
        self.max_tx_s = max_tx_s
        self.player = _pick_player(audio_device)
        self.sock = socket.create_connection(self.addr, timeout=3)
        self.f = self.sock.makefile("rw")

    @classmethod
    def from_config(cls, rc):
        """Build from the [radio] settings table."""
        return cls(rc.get("rigctld_host", "127.0.0.1"), int(rc.get("rigctld_port", 4532)),
                   rc.get("audio_device", "default"), max_tx_s=float(rc.get("max_tx_s", 320)),
                   data_mode=bool(rc.get("data_mode", True)), max_swr=float(rc.get("max_swr", 2.0)))

    def _cmd(self, text):
        with self._lock:
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

    def read_swr(self):
        """SWR from the rig's meter (1.0 = perfect), or None if the rig can't report it."""
        try:
            v = float(self._cmd("l SWR"))
        except (ValueError, RuntimeError, OSError):
            return None
        return v if v >= 1.0 else None if v <= 0 else 1.0

    def _swr_watch(self, done, trip, label):
        """While keyed, read SWR twice a second; above the limit, unkey at once."""
        if done.wait(0.5):                   # let the PA and meter settle
            return
        while not done.is_set():
            swr = self.read_swr()
            if swr is None:
                if not self._swr_warned:
                    self._swr_warned = True
                    log.warning("the radio does not report SWR through Hamlib - SWR protection is OFF")
                return
            self.last_swr = max(self.last_swr or 0, swr)
            if swr > self.max_swr:
                trip.append(swr)
                log.error("SWR %.1f above %.1f on %s - dropping PTT", swr, self.max_swr, label)
                try:
                    self._cmd("T 0")
                finally:
                    _stop_audio()
                return
            done.wait(self.swr_poll_s)

    def transmit(self, freq_hz, rig_mode, audio, fs, label):
        dur = len(audio) / fs
        if dur > self.max_tx_s:
            raise RuntimeError(f"{label}: {dur:.0f} s exceeds max_tx_s")
        tmp = os.path.join(tempfile.gettempdir(), f"uranus_{os.getpid()}.wav")
        write_wav(tmp, audio, fs)
        done, trip, watch = threading.Event(), [], None
        self.last_swr = None
        try:
            self._cmd("T 1")
            if self.max_swr > 0:
                watch = threading.Thread(target=self._swr_watch, args=(done, trip, label), daemon=True)
                watch.start()
            time.sleep(self.ptt_lead_s)
            if not trip:
                try:
                    self.player(tmp, audio, fs, dur)
                except Exception:            # noqa: BLE001
                    if not trip:             # audio cut by the SWR trip is expected
                        raise
        finally:
            done.set()
            if watch:
                watch.join(2)
            for _ in range(3):               # make very sure PTT drops
                try:
                    self._cmd("T 0")
                    break
                except Exception:            # noqa: BLE001
                    time.sleep(0.2)
            os.unlink(tmp)
        if trip:
            raise SWRError(trip[0], self.max_swr, label)

    # Data modes take the transmit audio from the rig's USB sound card instead of the
    # microphone (Icom USB-D / FM-D, Yaesu DATA-USB / DATA-FM). WSJT-X does the same.
    DATA_MODE = {"USB": "PKTUSB", "LSB": "PKTLSB", "FM": "PKTFM"}

    def tune(self, freq_hz, rig_mode):
        self._cmd(f"F {int(freq_hz)}")
        want = self.DATA_MODE.get(rig_mode, rig_mode) if self.data_mode else rig_mode
        try:
            self._cmd(f"M {want} 0")
        except RuntimeError:
            if want == rig_mode:
                raise
            if want not in getattr(self, "_warned", set()):
                self._warned = getattr(self, "_warned", set()) | {want}
                log.warning("This radio cannot be switched to %s through Hamlib, so Uranus uses plain %s. In plain "
                            "%s the radio must take its transmit audio from USB: on Icom rigs set the menu item "
                            "DATA OFF MOD to USB (voice from the microphone then needs it set back to MIC).",
                            want, rig_mode, rig_mode)
            self._cmd(f"M {rig_mode} 0")
        time.sleep(0.3)


def _pick_player(device):
    """Return play(path, audio, fs, dur) for this platform."""
    try:
        import sounddevice as sd             # optional; lets you pick the rig's sound card

        from .audiodev import resolve

        def play_sd(path, audio, fs, dur):
            idx = resolve(device, "out")
            try:
                info = sd.query_devices(idx if idx is not None else sd.default.device[1])
                name = info["name"]
            except Exception:                # noqa: BLE001
                name = "?"
            a = np.asarray(audio, float)
            rms = 20 * np.log10(np.sqrt(np.mean(a ** 2)) + 1e-12)
            log.info("TX audio -> '%s'%s, %.0f dBFS for %.1f s", name,
                     " (Windows default output - NOT the radio?)" if idx is None else "", rms, dur)
            if idx is None:
                log.warning("Audio to radio is set to 'default': transmit audio goes to the PC's default speakers. "
                            "Choose 'Speakers (USB Audio CODEC)' in Station setup.")
            sd.play(audio, fs, device=idx, blocking=True)
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
        p = _APLAY["p"] = subprocess.Popen(["aplay", "-q", "-D", device, path])
        try:
            p.wait(timeout=dur + 10)
        finally:
            _APLAY.pop("p", None)
    return play_aplay
