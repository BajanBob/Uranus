"""Spoken announcements: Windows speech (System.Speech through PowerShell), espeak / spd-say on Linux.
Never blocks the caller and never fails loudly: no speech engine means silence."""
import os
import queue
import shutil
import subprocess
import threading

_q = queue.Queue(maxsize=8)
_worker = None
ENABLED = False


def _engine(text):
    text = text.replace('"', "'")[:240]
    if os.name == "nt":
        ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f'$s.Rate = 1; $s.Speak("{text}")')
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], timeout=60, creationflags=flags,
                       capture_output=True)
    elif shutil.which("spd-say"):
        subprocess.run(["spd-say", "-w", text], timeout=60, capture_output=True)
    elif shutil.which("espeak"):
        subprocess.run(["espeak", text], timeout=60, capture_output=True)


def _run():
    while True:
        text = _q.get()
        try:
            _engine(text)
        except Exception:                         # noqa: BLE001
            pass


def say(text):
    """Queue a sentence (dropped if eight are already waiting or speech is off)."""
    global _worker
    if not ENABLED or not text:
        return False
    if _worker is None:
        _worker = threading.Thread(target=_run, daemon=True)
        _worker.start()
    try:
        _q.put_nowait(text)
        return True
    except queue.Full:
        return False


def spoken_call(call):
    """8P5AB -> '8 P 5 A B' so engines spell callsigns."""
    return " ".join(call)
