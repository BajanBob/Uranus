"""Plug-and-play radio control: Uranus starts Hamlib's rigctld for you.

The Windows download carries Hamlib in its `hamlib` folder, so nothing has to
be installed. When a CAT radio is needed, `ensure()`:

  1. uses a rigctld that is already running, if there is one;
  2. otherwise finds rigctld (bundled folder, PATH, or C:\\Program Files\\hamlib-*);
  3. looks up the radio's Hamlib model number from its name (rigctl -l);
  4. finds the COM port (the configured one, else the radio's USB serial chip);
  5. starts rigctld hidden in the background and checks the radio answers.

Hamlib is free software (LGPL/GPL) by the Hamlib project: https://hamlib.github.io
"""

import glob
import logging
import os
import shutil
import socket
import subprocess
import sys
import time

log = logging.getLogger("uranus.rigctl")

# Fallbacks if `rigctl -l` cannot be run. CI checks these against the bundled Hamlib.
KNOWN_MODELS = {"IC-9100": 3068, "IC-9700": 3081}

# USB serial chips used by rigs: Icom uses Silicon Labs CP210x; others FTDI / CH340 / Prolific.
_PORT_HINTS = ("cp210", "silicon labs", "icom", "ftdi", "ft232", "ch340", "ch341", "prolific", "usb serial")

_proc = None          # the rigctld Uranus started, so it can be stopped on exit
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hamlib_dirs():
    """Folders searched for rigctl/rigctld, bundled copy first."""
    b = _base()
    dirs = [os.path.join(b, "hamlib"), os.path.join(b, "hamlib", "bin")]
    if os.environ.get("URANUS_HAMLIB_DIR"):
        dirs.insert(0, os.environ["URANUS_HAMLIB_DIR"])
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            dirs += sorted(glob.glob(os.path.join(root, "hamlib*", "bin")), reverse=True)
    return dirs


def find_exe(name):
    exe = name + (".exe" if os.name == "nt" else "")
    for d in hamlib_dirs():
        p = os.path.join(d, exe)
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def _run(args, timeout=20):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          cwd=os.path.dirname(args[0]) or None, creationflags=_NO_WINDOW)


def model_list():
    """{model name upper: number} from `rigctl -l`, or {} if Hamlib is unavailable."""
    exe = find_exe("rigctl")
    if not exe:
        return {}
    try:
        out = _run([exe, "-l"]).stdout
    except Exception as e:                       # noqa: BLE001
        log.debug("rigctl -l failed: %s", e)
        return {}
    models = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit():
            for tok in parts[1:4]:
                models.setdefault(tok.upper(), int(parts[0]))
    return models


def model_for(hamlib_name):
    """Hamlib model number for a radio name such as 'IC-9100', or None."""
    if not hamlib_name:
        return None
    n = model_list().get(hamlib_name.upper())
    return n or KNOWN_MODELS.get(hamlib_name.upper())


def list_ports():
    try:
        import serial.tools.list_ports
        return [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]
    except Exception:                            # noqa: BLE001
        return []


def detect_port(preferred="", ports=None):
    """The configured port if it exists, else the most radio-like USB serial port."""
    ports = list_ports() if ports is None else ports
    devices = [d for d, _ in ports]
    if preferred and preferred in devices:
        return preferred
    for hint in _PORT_HINTS:
        for d, desc in ports:
            if hint in desc.lower():
                return d
    return devices[0] if len(devices) == 1 else (preferred or None)


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def read_frequency(host, port, timeout=4):
    """Ask rigctld for the radio's frequency in Hz (proves the radio is answering)."""
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        f = s.makefile("rw")
        f.write("f\n")
        f.flush()
        reply = f.readline().strip()
    if not reply or reply.startswith("RPRT"):
        raise RuntimeError(f"the radio did not answer ({reply or 'no reply'})")
    return int(float(reply))


def ensure(cfg, say=None):
    """Make sure rigctld is running and the radio answers. Returns a one-line status.
    Raises RuntimeError with a plain-English hint if it cannot."""
    from . import radios
    global _proc
    say = say or log.info
    rc = cfg.get("radio", {})
    host, tport = rc.get("rigctld_host", "127.0.0.1"), int(rc.get("rigctld_port", 4532))

    if port_open(host, tport):
        try:
            hz = read_frequency(host, tport)
            return f"Radio connected (rigctld already running): {hz / 1e6:.4f} MHz"
        except Exception:                        # noqa: BLE001
            if _proc is None:
                raise RuntimeError(f"Another rigctld is running on port {tport} but the radio is not answering. "
                                   "Close it (or the program that started it) and try again.")
            stop()

    exe = find_exe("rigctld")
    if not exe:
        raise RuntimeError("Hamlib (rigctld) was not found. It comes in the 'hamlib' folder of the Uranus "
                           "Windows download: keep that folder next to Uranus.exe.")
    prof = radios.BY_NAME.get(rc.get("profile", ""))
    model = rc.get("hamlib_model") or (model_for(prof.hamlib_name) if prof else None)
    if not model:
        raise RuntimeError("Uranus does not know this radio's Hamlib model. Choose your radio in the Setup "
                           "wizard, or pick 'Generic CAT rig' and enter its model number.")
    port = detect_port(rc.get("cat_port", ""))
    if not port:
        raise RuntimeError("No radio COM port found. Switch the radio on, plug in its USB cable, and install "
                           "its USB driver (Icom: 'USB Driver' from icomjapan.com).")
    baud = str(rc.get("cat_baud", 19200))
    logpath = os.path.join(_base(), "out", "rigctld.log")
    os.makedirs(os.path.dirname(logpath), exist_ok=True)
    say(f"Starting Hamlib rigctld: model {model}, {port} at {baud} baud")
    lf = open(logpath, "w")                      # noqa: SIM115 - kept open for the child process
    _proc = subprocess.Popen([exe, "-m", str(model), "-r", port, "-s", baud, "-t", str(tport)],
                             stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             cwd=os.path.dirname(exe), creationflags=_NO_WINDOW)
    t_end = time.time() + 8
    while time.time() < t_end and not port_open(host, tport):
        if _proc.poll() is not None:
            break
        time.sleep(0.25)
    if _proc.poll() is not None or not port_open(host, tport):
        stop()
        tail = _tail(logpath)
        raise RuntimeError(f"rigctld could not open {port}. Close any other program using the radio "
                           f"(WSJT-X, RS-BA1, another Uranus) and check the radio is on.\n{tail}")
    try:
        hz = read_frequency(host, tport)
    except Exception as e:                       # noqa: BLE001
        stop()
        raise RuntimeError(f"The radio on {port} is not answering: {e}. Check the radio's CI-V USB baud rate "
                           f"is {baud} and (Icom) CI-V USB Echo Back is OFF.") from None
    return f"Radio connected on {port}: {hz / 1e6:.4f} MHz"


def _tail(path, n=4):
    try:
        with open(path, errors="replace") as f:
            return "".join(f.readlines()[-n:]).strip()
    except OSError:
        return ""


def stop():
    """Stop the rigctld that Uranus started (if any)."""
    global _proc
    if _proc is not None:
        try:
            _proc.terminate()
            _proc.wait(timeout=3)
        except Exception:                        # noqa: BLE001
            pass
        _proc = None
