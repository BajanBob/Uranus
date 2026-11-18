"""Tune the radio by CAT (hamlib rigctld) for the WEFAX receiver and the scanner, and a continuous audio input."""
import logging
import threading

log = logging.getLogger("uranus.tuning")


def tune(cfg, mhz, rig_mode="USB"):
    """Tune the radio to `mhz` in `rig_mode`. Returns a sentence for the console. Without CAT control the
    radio is left alone and the sentence says what to set by hand."""
    rc, rx = cfg.get("radio", {}), cfg.get("receive", {})
    if rc.get("backend") != "hamlib" or rx.get("source", "audio") != "audio":
        return f"No CAT control: set the radio to {mhz:.4f} MHz {rig_mode} by hand."
    from . import rigctl
    from .radio import HamlibRadio
    rigctl.ensure(cfg)
    r = HamlibRadio.from_config(rc)
    try:
        r.tune(mhz * 1e6, rig_mode)
    finally:
        r.sock.close()
    return f"Radio tuned to {mhz:.4f} MHz {rig_mode}."


class AudioIn:
    """Continuous receive audio (mono float at fs) handed to `on_block` in small blocks, with no gaps between
    them. WEFAX needs this: one lost block would shear the picture. Also feeds the live waterfall."""

    def __init__(self, device, on_block, fs=12000):
        self.device, self.on_block, self.fs = device, on_block, fs
        self.stream, self.error = None, ""
        self._lock = threading.Lock()

    def start(self):
        import sounddevice as sd
        from . import spectrum
        from .audiodev import resolve

        def cb(data, frames, t, status):
            block = data[:, 0].astype(float)
            if self.fs == spectrum.FS:
                spectrum.publish(block)
            try:
                self.on_block(block)
            except Exception as e:                   # noqa: BLE001 - never kill the audio thread
                self.error = str(e)
                log.warning("audio consumer error: %s", e)
        spectrum.external(True)
        try:
            self.stream = sd.InputStream(samplerate=self.fs, channels=1, dtype="float32",
                                         device=resolve(self.device, "in"), blocksize=1200, callback=cb)
            self.stream.start()
        except Exception:
            spectrum.external(False)
            raise

    def stop(self):
        from . import spectrum
        with self._lock:
            if self.stream is not None:
                try:
                    self.stream.stop()
                    self.stream.close()
                finally:
                    self.stream = None
                    spectrum.external(False)
