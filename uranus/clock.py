"""NTP-corrected clock for slot timing.

Asks NTP servers (SNTP, UDP port 123) how far this PC's clock is off and applies the correction inside
Uranus, so transmissions start on the exact 3-minute marks and FT8 / WSPR slots line up with the world,
even when Windows time is a second or two out. Re-checks every 30 minutes in the background.

    clock.now()        corrected time.time()
    clock.offset()     seconds added to the PC clock (None until the first successful check)
    clock.status()     one-line description for the window
"""

import logging
import socket
import struct
import threading
import time

log = logging.getLogger("uranus.clock")

SERVERS = ("pool.ntp.org", "time.windows.com", "time.google.com", "time.cloudflare.com")
_NTP_EPOCH = 2208988800                       # seconds from 1900 to 1970
_state = {"offset": None, "server": "", "checked": 0.0, "delay": None, "error": ""}
_lock = threading.Lock()
_thread = None


def query(server, timeout=2.0):
    """(offset_s, round_trip_s) from one SNTP exchange."""
    pkt = bytearray(48)
    pkt[0] = 0x23                             # LI 0, version 4, mode 3 (client)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        t0 = time.time()
        s.sendto(pkt, (server, 123))
        data, _ = s.recvfrom(512)
        t3 = time.time()
    if len(data) < 48:
        raise ValueError("short NTP reply")
    if data[1] == 0 or (data[0] & 0x07) not in (4, 5):
        raise ValueError("NTP server not synchronised")

    def ts(i):
        sec, frac = struct.unpack("!II", data[i:i + 8])
        return sec - _NTP_EPOCH + frac / 2 ** 32
    t1, t2 = ts(32), ts(40)                   # server receive, server transmit
    return ((t1 - t0) + (t2 - t3)) / 2, (t3 - t0) - (t2 - t1)


def sync(servers=SERVERS):
    """Check the clock now. Uses the reply with the shortest round trip. Returns the offset or None."""
    best, err = None, ""
    for srv in servers:
        try:
            for _ in range(3):
                off, rtt = query(srv)
                if best is None or rtt < best[1]:
                    best = (off, rtt, srv)
        except Exception as e:                # noqa: BLE001
            err = f"{srv}: {e}"
        if best and best[1] < 0.15:
            break
    with _lock:
        _state["checked"] = time.time()
        if best:
            _state.update(offset=best[0], delay=best[1], server=best[2], error="")
        else:
            _state["error"] = err or "no NTP server answered"
    if best:
        lvl = log.warning if abs(best[0]) > 1.0 else log.info
        lvl("NTP (%s): PC clock is %+.3f s %s; Uranus corrects for it", best[2], -best[0],
            "fast" if best[0] < 0 else "slow")
    else:
        log.warning("NTP check failed (%s) - using the PC clock as it is", _state["error"])
    return _state["offset"]


def start(every_s=1800):
    """Check now (in the background) and then every `every_s` seconds."""
    global _thread
    if _thread and _thread.is_alive():
        return

    def loop():
        while True:
            sync()
            time.sleep(every_s)
    _thread = threading.Thread(target=loop, daemon=True, name="ntp")
    _thread.start()


def offset():
    return _state["offset"]


def now():
    off = _state["offset"]
    return time.time() + (off or 0.0)


def status():
    off = _state["offset"]
    if off is None:
        return "NTP: not checked yet" if not _state["error"] else f"NTP: unavailable ({_state['error']})"
    return (f"NTP synced via {_state['server']}: PC clock {abs(off):.2f} s "
            f"{'fast' if off < 0 else 'slow'}, corrected")


def set_offset(value):
    """For tests."""
    with _lock:
        _state["offset"] = value
