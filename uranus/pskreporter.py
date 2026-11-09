"""PSK Reporter client.

Upload: reception reports as IPFIX over UDP to report.pskreporter.info:4739
        (test server port 14739), following the PSK Reporter developer spec:
        a receiver record (template 0x9992) and sender records (0x9993),
        enterprise number 30351. Reports are batched and sent at most every
        5 minutes, each spot once, as PSK Reporter asks of client software.
Query:  who heard a callsign, from retrieve.pskreporter.info (XML).

Only PSK Reporter is used: it accepts any mode name, so Pumpkin and UR spots
appear there as mode "PUMPKIN" / "UR". WSPRnet accepts only WSPR/FST4W spots,
so Uranus never sends Pumpkin decodes to it.
"""

import logging
import random
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import __version__

log = logging.getLogger("uranus.psk")

HOST = "report.pskreporter.info"
PORT_LIVE, PORT_TEST = 4739, 14739
ENTERPRISE = 30351
RX_TEMPLATE, TX_TEMPLATE = 0x9992, 0x9993
VAR = 0xFFFF

# (field id, length) - VAR means a length-prefixed string
RX_FIELDS = [(2, VAR), (4, VAR), (8, VAR)]               # receiverCallsign, receiverLocator, decoderSoftware
TX_FIELDS = [(1, VAR), (5, 4), (6, 1), (10, VAR), (3, VAR), (11, 1)]
# senderCallsign, frequency, sNR, mode, senderLocator, informationSource; + flowStartSeconds (IANA 150)


def _pad4(b):
    return b + b"\x00" * (-len(b) % 4)


def _field_specs(fields):
    out = b""
    for fid, length in fields:
        out += struct.pack(">HHI", 0x8000 | fid, length, ENTERPRISE)
    return out


def _templates():
    rx = struct.pack(">HHH", RX_TEMPLATE, len(RX_FIELDS), 0) + _field_specs(RX_FIELDS)
    rx_set = _pad4(struct.pack(">HH", 3, 0) + rx)
    rx_set = rx_set[:2] + struct.pack(">H", len(rx_set)) + rx_set[4:]
    tx = struct.pack(">HH", TX_TEMPLATE, len(TX_FIELDS) + 1) + _field_specs(TX_FIELDS) \
        + struct.pack(">HH", 150, 4)                     # flowStartSeconds
    tx_set = _pad4(struct.pack(">HH", 2, 0) + tx)
    tx_set = tx_set[:2] + struct.pack(">H", len(tx_set)) + tx_set[4:]
    return rx_set + tx_set


def _s(text):
    b = str(text).encode("ascii", "replace")[:254]
    return bytes([len(b)]) + b


def _data_set(template_id, records):
    body = b"".join(records)
    s = _pad4(struct.pack(">HH", template_id, 0) + body)
    return s[:2] + struct.pack(">H", len(s)) + s[4:]


def build_packet(rx_call, rx_grid, spots, seq, domain):
    rx_rec = _s(rx_call) + _s(rx_grid) + _s(f"Uranus {__version__}")
    tx_recs = []
    for sp in spots:
        snr = max(-128, min(127, int(round(sp["snr"]))))
        tx_recs.append(_s(sp["call"]) + struct.pack(">I", int(sp["freq_hz"])) + struct.pack(">b", snr)
                       + _s(sp["mode"]) + _s(sp["grid"]) + b"\x01" + struct.pack(">I", int(sp["time"])))
    body = _templates() + _data_set(RX_TEMPLATE, [rx_rec]) + _data_set(TX_TEMPLATE, tx_recs)
    header = struct.pack(">HHIII", 10, 16 + len(body), int(time.time()), seq, domain)
    return header + body


class Reporter:
    """Collects spots and uploads them in batches from a background thread."""

    def __init__(self, rx_call, rx_grid, test=True, interval_s=300):
        self.rx_call, self.rx_grid = rx_call, rx_grid
        self.addr = (HOST, PORT_TEST if test else PORT_LIVE)
        self.interval_s = interval_s
        self.domain = random.getrandbits(32)
        self.seq = 0
        self.pending = []
        self.lock = threading.Lock()
        self.stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def add(self, spot):
        with self.lock:
            key = (spot["call"], spot["mode"], int(spot["time"]) // 60)
            if all((p["call"], p["mode"], int(p["time"]) // 60) != key for p in self.pending):
                self.pending.append(spot)

    def flush(self):
        with self.lock:
            batch, self.pending = self.pending[:50], self.pending[50:]
        if not batch:
            return 0
        pkt = build_packet(self.rx_call, self.rx_grid, batch, self.seq, self.domain)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(pkt, self.addr)
            self.seq += len(batch)
            log.info("PSK Reporter: sent %d spot(s) to %s:%d", len(batch), *self.addr)
        except OSError as e:
            log.warning("PSK Reporter upload failed (%s); will retry", e)
            with self.lock:
                self.pending = batch + self.pending
            return 0
        return len(batch)

    def _loop(self):
        self.stop.wait(random.uniform(30, 90))
        while not self.stop.is_set():
            self.flush()
            self.stop.wait(self.interval_s + random.uniform(0, 30))


def heard_by(callsign, seconds=3600, contact=None, timeout=20):
    """Reception reports of `callsign` from PSK Reporter (stations that heard us)."""
    q = {"senderCallsign": callsign, "flowStartSeconds": -int(seconds), "rronly": 1, "noactive": 1}
    if contact:
        q["appcontact"] = contact
    url = "https://retrieve.pskreporter.info/query?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": f"Uranus/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        root = ET.fromstring(r.read())
    out = []
    for rr in root.iter("receptionReport"):
        a = rr.attrib
        if not a.get("receiverLocator"):
            continue
        out.append({"time": int(a.get("flowStartSeconds", time.time())), "call": a.get("receiverCallsign", "?"),
                    "grid": a["receiverLocator"][:6], "snr": float(a.get("sNR", "nan") or "nan"),
                    "freq_hz": int(a.get("frequency", 0) or 0), "mode": a.get("mode", "?"),
                    "direction": "heard"})
    return out
