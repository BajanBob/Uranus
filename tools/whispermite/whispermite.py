#!/usr/bin/env python3
"""
whispermite.py - Raspberry Pi companion for the Kanga WhisperMite (KWM)
WSPR / QRSS beacon.

What it does
  detect     Find the USB serial port and a baud rate that gives readable text
  monitor    Show (and optionally log) everything the WhisperMite prints
  configure  Push your callsign / locator / bands / QRSS settings from an INI file
  show       Enter the setup menu and print current settings ('?'), then exit
  send       Enter the setup menu and send one raw command (e.g. "I 10")
  sync       Press the Sync button via GPIO at the exact start of a minute,
             timed from the Pi's NTP-disciplined clock
  freqs      Print common WSPR transmit frequencies for the F1 / F2 commands

Requirements
  pip install pyserial            (Raspberry Pi OS: sudo apt install python3-serial)
  gpiozero (preinstalled on Raspberry Pi OS) - only for 'sync' and automatic
  button presses. Without the GPIO wiring the script asks YOU to press the button.

IMPORTANT: opening the serial port resets the WhisperMite (the CH340 toggles DTR,
like an Arduino). 'sync' therefore never touches the serial port.
"""

import argparse
import configparser
import datetime as dt
import glob
import re
import subprocess
import sys
import time

DEFAULT_INI = "whispermite.ini"
SETUP_PROMPT = re.compile(r"press\s+button", re.I)
VALID_DBM = {0, 3, 7, 10, 13, 17, 20, 23, 27, 30, 33, 37, 40, 43, 47, 50, 53, 57, 60}

# Transmit frequencies in MHz (USB dial + 1.5 kHz, middle of the 200 Hz WSPR window).
# 60m differs by country - check your licence and band plan before using it.
WSPR_FREQS = {
    "60m": 5.3662, "40m": 7.0401, "30m": 10.1402, "20m": 14.0971,
    "15m": 21.0961, "12m": 24.9261, "10m": 28.1261,
}


# --------------------------------------------------------------------------- utils
def log(msg):
    print(f"[{dt.datetime.utcnow():%H:%M:%S}Z] {msg}", flush=True)


def load_config(path):
    cfg = configparser.ConfigParser()
    if not cfg.read(path):
        sys.exit(f"Config file not found: {path}  (copy whispermite.ini and edit it)")
    return cfg


def find_port(preferred=None):
    if preferred and preferred != "auto":
        return preferred
    ports = sorted(glob.glob("/dev/serial/by-id/*1a86*") +  # CH340 vendor id
                   glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*"))
    if not ports:
        sys.exit("No USB serial device found. Use a DATA cable (not charge-only) "
                 "and check 'ls /dev/ttyUSB*'.")
    return ports[0]


def open_serial(port, baud):
    try:
        import serial
    except ImportError:
        sys.exit("pyserial missing: sudo apt install python3-serial")
    try:
        return serial.Serial(port, baud, timeout=0.2)
    except serial.SerialException as e:
        sys.exit(f"Cannot open {port}: {e}\nTip: sudo usermod -aG dialout $USER, then log out/in.")


def read_for(ser, seconds, echo=True, stop=None):
    """Read lines for up to `seconds`. Returns all text. Stops early if regex `stop` matches."""
    buf, end = "", time.time() + seconds
    while time.time() < end:
        chunk = ser.read(256).decode("ascii", errors="replace")
        if chunk:
            buf += chunk
            if echo:
                sys.stdout.write(chunk)
                sys.stdout.flush()
            if stop and stop.search(buf):
                return buf
    return buf


# --------------------------------------------------------------------------- button
class SyncButton:
    """Drives the Sync button through an optocoupler/transistor on a GPIO pin.
    If no pin is configured, falls back to asking the human to press it."""

    def __init__(self, pin=None, press_ms=150):
        self.press_s = press_ms / 1000.0
        self.dev = None
        if pin is not None:
            try:
                from gpiozero import OutputDevice
                self.dev = OutputDevice(pin, active_high=True, initial_value=False)
            except Exception as e:  # noqa: BLE001
                log(f"GPIO unavailable ({e}); you will need to press the button by hand.")

    @property
    def automatic(self):
        return self.dev is not None

    def press(self, label="Sync"):
        if self.dev:
            self.dev.on()
            time.sleep(self.press_s)
            self.dev.off()
        else:
            print(f"\n>>> PRESS THE {label.upper()} BUTTON NOW <<<\n", flush=True)


def button_from(cfg, args=None):
    pin = cfg.get("gpio", "sync_pin", fallback="").strip()
    if args is not None and getattr(args, "manual", False):
        pin = ""
    return SyncButton(int(pin) if pin else None,
                      cfg.getint("gpio", "press_ms", fallback=150))


# --------------------------------------------------------------------------- menu
class Menu:
    """Session inside the WhisperMite setup menu (it times out after 60 s idle)."""

    def __init__(self, ser, line_end="\r\n", gap=1.0):
        self.ser, self.eol, self.gap = ser, line_end, gap

    def cmd(self, text, wait=None):
        log(f"-> {text}")
        self.ser.write((text + self.eol).encode("ascii"))
        self.ser.flush()
        return read_for(self.ser, wait or self.gap)


def enter_menu(cfg, args):
    port = find_port(args.port or cfg.get("serial", "port", fallback="auto"))
    baud = args.baud or cfg.getint("serial", "baud", fallback=9600)
    btn = button_from(cfg, args)
    log(f"Opening {port} @ {baud} (this resets the WhisperMite)")
    ser = open_serial(port, baud)
    ser.reset_input_buffer()
    # Do NOT press during the ~5 s mode-select window - that would change mode.
    log("Waiting for 'Press Button to enter setup' ...")
    text = read_for(ser, 25, stop=SETUP_PROMPT)
    if not SETUP_PROMPT.search(text):
        ser.close()
        sys.exit("\nNever saw the setup prompt. Check baud rate ('detect'), and that the "
                 "internal config-lock switch (Option 1) is OFF.")
    time.sleep(0.2)
    btn.press("Sync")
    read_for(ser, 4 if btn.automatic else 8)
    eol = {"crlf": "\r\n", "cr": "\r", "lf": "\n"}[cfg.get("serial", "line_end", fallback="crlf")]
    return ser, Menu(ser, eol, cfg.getfloat("serial", "command_gap_s", fallback=1.0))


# --------------------------------------------------------------------------- validation
def build_commands(cfg):
    w = cfg["wspr"]
    call = w.get("callsign", "").strip().upper()
    loc = w.get("locator", "").strip().upper()
    pwr = w.getint("power_dbm", 23)
    errs = []
    if not call or call in ("N0CALL", "NOCALL"):
        errs.append("Set your real callsign in [wspr] callsign")
    elif len(call) > 6 or not re.fullmatch(r"[A-Z0-9]+", call):
        errs.append("WSPR callsign must be up to 6 letters/digits, no '/'")
    if not re.fullmatch(r"[A-R]{2}[0-9]{2}", loc):
        errs.append("Locator must be 4 characters, e.g. GK03")
    if pwr not in VALID_DBM:
        errs.append(f"power_dbm must be one of {sorted(VALID_DBM)} (200 mW = 23)")
    interval = w.getint("interval_min", 10)
    if interval < 2 or interval % 2:
        errs.append("interval_min must be an even number >= 2")
    band = w.get("band", "DUAL").strip().upper()
    if band not in ("1", "2", "DUAL"):
        errs.append("band must be 1, 2 or DUAL")
    if errs:
        sys.exit("Config errors:\n  - " + "\n  - ".join(errs))

    cmds = [f"Q {call} {loc} {pwr}",
            f"F1 {w.getfloat('f1_mhz'):.4f}",
            f"F2 {w.getfloat('f2_mhz'):.4f}",
            f"B {band}",
            f"I {interval}"]
    if w.get("correction", "").strip():
        cmds.append(f"C {w.getint('correction')}")

    if cfg.getboolean("qrss", "enabled", fallback=False):
        q = cfg["qrss"]
        cmds += [f"QC {q.get('callsign', call).strip().upper()}",
                 f"QF {q.getfloat('freq_mhz'):.4f}",
                 f"QM {q.get('mode', 'FSK').strip().upper()}",
                 f"QD {q.getint('dot_ms', 3000)}",
                 f"QP {q.getint('pattern', 0)}",
                 f"QS {q.getint('shift_hz', 5)}"]
    return cmds


def random_shift_state(text):
    """Try to read the random-shift state from the '?' listing. None = unknown."""
    for line in text.splitlines():
        if "rand" in line.lower():
            if re.search(r"\bon\b|enabled|yes", line, re.I):
                return True
            if re.search(r"\boff\b|disabled|\bno\b", line, re.I):
                return False
    return None


# --------------------------------------------------------------------------- commands
def cmd_configure(cfg, args):
    cmds = build_commands(cfg)
    want_random = cfg.getboolean("wspr", "random_shift", fallback=True)
    if args.dry_run:
        print("\n".join(cmds + [f"(R toggled if needed -> random shift {'ON' if want_random else 'OFF'})", "?", "X"]))
        return
    ser, menu = enter_menu(cfg, args)
    try:
        for c in cmds:
            menu.cmd(c)
        state = random_shift_state(menu.cmd("?", wait=2.5))
        if state is None:
            log("Could not read random-shift state from '?'; leaving R unchanged.")
        elif state != want_random:
            menu.cmd("R")
        menu.cmd("?", wait=2.5)
        menu.cmd("X", wait=3)
        log("Saved to EEPROM and exited. Now run:  whispermite.py sync")
    finally:
        ser.close()


def cmd_show(cfg, args):
    ser, menu = enter_menu(cfg, args)
    try:
        menu.cmd("?", wait=3)
        menu.cmd("F", wait=2)
        menu.cmd("X", wait=2)
    finally:
        ser.close()


def cmd_send(cfg, args):
    ser, menu = enter_menu(cfg, args)
    try:
        menu.cmd(args.command, wait=2)
        if not args.stay:
            menu.cmd("X", wait=2)
    finally:
        ser.close()


def cmd_monitor(cfg, args):
    port = find_port(args.port or cfg.get("serial", "port", fallback="auto"))
    baud = args.baud or cfg.getint("serial", "baud", fallback=9600)
    ser = open_serial(port, baud)
    out = open(args.log, "a") if args.log else None
    log(f"Monitoring {port} @ {baud}  (Ctrl+C to stop)")
    line = ""
    try:
        while True:
            chunk = ser.read(256).decode("ascii", errors="replace")
            for ch in chunk:
                if ch in "\r\n":
                    if line.strip():
                        stamp = f"{dt.datetime.utcnow():%Y-%m-%d %H:%M:%S}Z"
                        print(f"{stamp}  {line}", flush=True)
                        if out:
                            out.write(f"{stamp}  {line}\n")
                            out.flush()
                    line = ""
                else:
                    line += ch
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
        if out:
            out.close()


def cmd_detect(cfg, args):
    port = find_port(args.port or cfg.get("serial", "port", fallback="auto"))
    log(f"Port: {port}")
    best = None
    for baud in (9600, 115200, 57600, 38400, 19200):
        ser = open_serial(port, baud)
        text = read_for(ser, 6, echo=False)
        ser.close()
        printable = sum(c.isprintable() or c in "\r\n" for c in text)
        score = printable / len(text) if text else 0
        log(f"  {baud:>6} baud: {len(text):4d} chars, {score:.0%} readable")
        if text and score > 0.9 and (best is None or score > best[1]):
            best = (baud, score)
        time.sleep(1)
    if best:
        log(f"Use baud = {best[0]} in whispermite.ini")
    else:
        log("No clean text found. Check the cable/driver and try again.")


def ntp_synced():
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out == "yes"
    except Exception:  # noqa: BLE001
        return None


def cmd_sync(cfg, args):
    btn = button_from(cfg, args)
    synced = ntp_synced()
    if synced is False and not args.force:
        sys.exit("The Pi clock is NOT NTP-synchronised. Connect to the internet (or add "
                 "a GPS) and retry, or use --force.")
    if synced is None:
        log("Could not verify NTP status (timedatectl missing) - make sure the clock is right.")

    every = args.every or cfg.getint("sync", "boundary_min", fallback=10)
    offset = (args.offset_ms if args.offset_ms is not None
              else cfg.getint("sync", "offset_ms", fallback=0)) / 1000.0
    now = time.time()
    period = every * 60
    target = (int(now // period) + 1) * period
    if target - now < 15:                     # too close - take the next one
        target += period
    log(f"Will press Sync at {dt.datetime.utcfromtimestamp(target):%H:%M:%S}Z "
        f"({target - now:.0f} s from now)")
    if not btn.automatic:
        log("No GPIO configured - I'll count you down; press on ZERO.")

    press_at = target + offset
    shown = None
    while True:
        remaining = press_at - time.time()
        if remaining <= 0:
            break
        if not btn.automatic:
            sec = int(remaining) + 1
            if sec <= 5 and sec != shown:
                print(f"   {sec}...", flush=True)
                shown = sec
        if remaining > 0.6:
            time.sleep(min(remaining - 0.5, 0.2))
        # last ~0.5 s: tight loop for millisecond accuracy
    btn.press("Sync")
    log(f"Pressed at {dt.datetime.utcnow():%H:%M:%S.%f}"[:-3] + "Z. The two TX Tones LEDs "
        "should blink ~5 times to confirm.")


def cmd_freqs(cfg, args):
    print("Band   F (MHz)   -> use with F1 / F2, e.g.  F1 7.0401")
    for band, f in WSPR_FREQS.items():
        print(f"{band:>4}   {f:.4f}")
    print("\nYour unit only covers its build version: Low 60/40, Mid 30/20, High 15/12/10.")


# --------------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description="Kanga WhisperMite helper for Raspberry Pi")
    p.add_argument("-c", "--config", default=DEFAULT_INI)
    p.add_argument("--port", help="serial port (default: auto)")
    p.add_argument("--baud", type=int)
    p.add_argument("--manual", action="store_true", help="ignore GPIO; prompt me to press")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("detect")
    m = sub.add_parser("monitor")
    m.add_argument("--log", help="append timestamped lines to this file")
    c = sub.add_parser("configure")
    c.add_argument("--dry-run", action="store_true", help="print commands only")
    sub.add_parser("show")
    s = sub.add_parser("send")
    s.add_argument("command", help='raw menu command, e.g. "I 10"')
    s.add_argument("--stay", action="store_true", help="don't send X afterwards")
    y = sub.add_parser("sync")
    y.add_argument("--every", type=int, help="press on the next N-minute boundary (default 10)")
    y.add_argument("--offset-ms", type=int, help="fine-tune press timing (+late / -early)")
    y.add_argument("--force", action="store_true", help="sync even if NTP is not confirmed")
    sub.add_parser("freqs")

    args = p.parse_args()
    cfg = load_config(args.config) if args.cmd != "freqs" else configparser.ConfigParser()
    {"detect": cmd_detect, "monitor": cmd_monitor, "configure": cmd_configure,
     "show": cmd_show, "send": cmd_send, "sync": cmd_sync, "freqs": cmd_freqs}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
