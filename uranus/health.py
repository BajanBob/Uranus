"""Station health check: everything Uranus needs, on one screen, each with a fix."""
import os
import shutil
import socket


def check(cfg, audio=True, cat=True, net=True, record=None):
    """[(name, status 'ok'|'warn'|'fail', detail, fix)]"""
    out = []
    st = cfg.get("station", {})
    call = st.get("callsign", "N0CALL")
    out.append(("Callsign", "ok" if call and call != "N0CALL" else "fail", f"{call} · {st.get('grid', '?')}",
                "" if call != "N0CALL" else "Setup wizard: enter your callsign and grid."))
    if audio:
        try:
            import numpy as np
            from . import monitor
            x = (record or monitor.record)(3, cfg.get("receive", {}).get("audio_device", "default"))
            lvl = float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))
            peak = float(np.max(np.abs(x))) if len(x) else 0.0
            if peak > 0.98:
                out.append(("Receive audio", "warn", f"{lvl:.0f} dBFS, clipping", "Turn the radio's USB audio level or "
                            "the Windows input level down."))
            elif lvl < -50:
                out.append(("Receive audio", "warn", f"{lvl:.0f} dBFS, very low", "Raise the Windows input level "
                            "(and the radio's USB audio level if it has one); aim for -40 to -20 dBFS."))
            else:
                out.append(("Receive audio", "ok", f"{lvl:.0f} dBFS", ""))
        except Exception as e:                    # noqa: BLE001
            out.append(("Receive audio", "fail", str(e)[:80], "Station setup: pick the radio's USB audio input, "
                        "then Refresh."))
    try:
        from . import clock
        off = clock.offset()
        if off is None and net:
            clock.sync()
            off = clock.offset()
        if off is None:
            out.append(("Clock", "warn", "not checked against internet time", "Connect to the internet once; FT8 "
                        "and WSPR need the clock within about 1 second."))
        else:
            out.append(("Clock", "ok" if abs(off) < 1 else "warn", f"PC clock off by {off:+.2f} s (corrected)",
                        "" if abs(off) < 1 else "Uranus corrects it; also fix Windows time (Settings > Time)."))
    except Exception as e:                        # noqa: BLE001
        out.append(("Clock", "warn", str(e)[:80], ""))
    rc = cfg.get("radio", {})
    if rc.get("backend", "dry-run") != "hamlib":
        out.append(("Radio control (CAT)", "warn", f"backend is {rc.get('backend', 'dry-run')}",
                    "Setup wizard: choose your radio so Uranus can tune it and key the transmitter."))
    elif cat:
        try:
            from . import rigctl
            out.append(("Radio control (CAT)", "ok", rigctl.ensure(cfg), ""))
        except Exception as e:                    # noqa: BLE001
            out.append(("Radio control (CAT)", "fail", str(e)[:100], "Check the USB cable, the radio's CI-V "
                        "settings and the COM port in Station setup."))
    swr = float(rc.get("max_swr", 0) or 0)
    out.append(("SWR protection", "ok" if swr else "warn", f"limit {swr:.1f}" if swr else "off",
                "" if swr else "Station setup: set a maximum SWR (2.0 is typical)."))
    from . import wsjt
    for exe in ("jt9", "wsprd"):
        try:
            wsjt.decoder_path(exe)
            out.append((f"Decoder {exe}", "ok", "found", ""))
        except Exception:                         # noqa: BLE001
            out.append((f"Decoder {exe}", "warn", "not found", "Install WSJT-X for FT8, FT4, Q65, JT65, FST4 and "
                        "WSPR decoding."))
    try:
        free = shutil.disk_usage(os.getcwd()).free / 1e9
        out.append(("Disk space", "ok" if free > 1 else "warn", f"{free:.1f} GB free",
                    "" if free > 1 else "Free some space: charts and logs need room."))
    except OSError:
        pass
    if net:
        try:
            socket.create_connection(("report.pskreporter.info", 4739), timeout=3).close()
            out.append(("Internet", "ok", "PSK Reporter reachable", ""))
        except OSError:
            try:
                socket.getaddrinfo("pskreporter.info", 80)
                out.append(("Internet", "ok", "online", ""))
            except OSError:
                out.append(("Internet", "warn", "offline", "Uranus works offline; spots upload when you reconnect."))
    out.append(("Noise filter", "ok" if cfg.get("receive", {}).get("noise_filter", True) else "warn",
                "on" if cfg.get("receive", {}).get("noise_filter", True) else "off",
                "" if cfg.get("receive", {}).get("noise_filter", True) else "Turn it on under the spectrum."))
    return out


def score(results):
    pts = {"ok": 1.0, "warn": 0.5, "fail": 0.0}
    return round(100 * sum(pts[r[1]] for r in results) / max(1, len(results)))
