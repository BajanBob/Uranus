"""Windows CI: open every window, drive the wizard and PSK Reporter panel, save screenshots."""
import os
import sys
import time

sys.path.insert(0, os.getcwd())
import tkinter.messagebox as _mb             # noqa: E402

DIALOGS = []


def _no_modal(name):                        # a dialog in CI would wait forever: log it and answer "yes/OK"
    def f(title="", message="", **kw):
        DIALOGS.append((name, title, message))
        print(f"DIALOG {name}: {title}: {message}", flush=True)
        return True
    return f


for _n in ("showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel", "askokcancel"):
    setattr(_mb, _n, _no_modal(_n))

import uranus.gui as g                      # noqa: E402

shots = os.path.join(os.getcwd(), "screenshots")
os.makedirs(shots, exist_ok=True)


def snap(win, name):
    win.update()
    time.sleep(0.4)
    win.update()
    try:
        from PIL import ImageGrab
        x, y = win.winfo_rootx(), win.winfo_rooty()
        ImageGrab.grab((x, y, x + win.winfo_width(), y + win.winfo_height())).save(os.path.join(shots, name))
    except Exception as e:                  # noqa: BLE001
        print("screenshot skipped:", e)


a = g.App()
a.geometry("1120x740+0+0")
a.update()
for w in a.winfo_children():                # the first-run wizard may have opened
    if isinstance(w, g.SetupWizard):
        w.destroy()
a.print("Listening for PUMPKIN-60 on 144.4900 MHz dial\n10:31:00 DECODE K4XYZ EM73 -21.3 dB 144.491500 MHz\n")
# waterfall: synthetic rows with a carrier near 1500 Hz, rendered directly so errors surface
import numpy as np                          # noqa: E402
rng = np.random.default_rng(1)
for k in range(140):
    row = rng.normal(-60, 3, 512)
    row[255 + (k % 3)] += 25
    row[100] += 12
    a.wf_rows.append(row)
a._render_waterfall()
# decoder status and alerts
class FakeRunner:                           # noqa: E302
    submode = "PUMPKIN-60"
    stop = None
a.runner = FakeRunner()
now = time.time()
a.dec = {"type": "recording", "start": now - 20, "end": now + 37, "submode": "PUMPKIN-60", "dial_hz": 144.49e6,
         "period": 60, "rec_s": 57}
a.update_decoder()
a.evq.put({"type": "result", "start": now - 60, "count": 0, "level_db": -32, "submode": "PUMPKIN-60",
           "dial_hz": 144.49e6, "period": 60, "rec_s": 57})
a.handle_events_extra()
a.on_decode({"call": "K4XYZ", "grid": "EM73", "snr": -21.3, "freq_hz": 144491500, "mode": "PUMPKIN"})
a.evq.put({"type": "heard_you", "r": {"call": "W1ABC", "grid": "FN42", "snr": -18.0, "freq_hz": 144491500,
                                       "mode": "PUMPKIN", "time": int(now)}})
a.handle_events_extra()
assert len(a.ticker_items) == 2, a.ticker_items
# red while keyed, blue while listening in the gap, SWR trip alert
FakeRunner.listen_in_gaps = True
a.set_state("air")
a.evq.put({"type": "tx_start", "label": "ft8", "freq_mhz": 14.074, "mode": "ft8", "seconds": 12.6})
a.handle_events_extra()
assert a.state == "tx" and a.state_lbl.cget("text") == "TRANSMITTING", a.state
a.evq.put({"type": "tx_end", "label": "ft8", "swr": 1.3})
a.handle_events_extra()
assert a.state == "listen", a.state
a.evq.put({"type": "swr_trip", "swr": 3.1, "limit": 2.0, "freq_mhz": 14.074, "band": "20m", "label": "ft8"})
a.handle_events_extra()
assert len(a.ticker_items) == 3, a.ticker_items
assert a.st_rows == {} and "Beacon bands" not in a.st_rows   # Station card removed
for _ in range(30):
    a.scroll_ticker()
a.update_decoder()
a.on_identified([
    {"mode": "FT8", "family": "ft8", "freq_hz": 1219, "bw_hz": 50, "confidence": 0.94, "snr_db": -12, "seen": 3,
     "reasons": ["6.25 baud", "about 8 tones wide", "starts 0.5 s into a 15 s UTC slot"]},
    {"mode": "PUMPKIN-15", "family": "pumpkin", "freq_hz": 1500, "bw_hz": 24, "confidence": 0.82, "snr_db": -5,
     "seen": 1, "reasons": ["24.95 baud", "MSK-like spectrum", "13.4 s long"]},
    {"mode": "Carrier", "family": "", "freq_hz": 2500, "bw_hz": 1, "confidence": 0.72, "snr_db": 3, "seen": 1,
     "reasons": ["steady, unmodulated"]},
    {"mode": "Unknown", "family": "", "freq_hz": 700, "bw_hz": 30, "confidence": 0.2, "snr_db": -9, "seen": 1,
     "reasons": ["30 Hz wide"]}])
a.dec = {"type": "idle"}                    # dial from the MHz box
a.on_decode({"call": "K1ABC", "grid": "FN42", "snr": -12, "freq_hz": int(float(a.v_dial.get().split()[0]) * 1e6) + 1219,
             "mode": "FT8"})
labels = [a.wf.itemcget(i, "text") for i in a.wf.find_withtag("tag") if a.wf.type(i) == "text"]
assert "K1ABC" in labels and "PUMPKIN-15 82%" in labels and "FT8 94%" not in labels, labels   # decode replaces guess
assert "Unknown" not in " ".join(labels) and "K1ABC" in a.pb_text.cget("text"), a.pb_text.cget("text")
snap(a, "1-faceplate.png")
a.runner = None

wz = g.SetupWizard(a)
wz.geometry("+60+40")
wz.v["call"].set("8P5AB")
wz.v["grid"].set("GK03ec")
wz.v["profile"].set("Icom IC-9100")
wz._apply_profile()
wz.goto(1)
wz.next()                                   # leaving a page saves what is done so far
assert g.load_cfg()["station"]["callsign"] == "8P5AB", "wizard did not save page by page"
for i in range(len(wz.STEPS)):
    wz.goto(i)
    assert wz.validate(i) is True or wz.v["backend"].get() == "hamlib", wz.validate(i)
    snap(wz, f"2-wizard-{i + 1}.png")
wz.v["backend"].set("dry-run")
wz.goto(5)
wz.finish()
a.update()
cfg = g.load_cfg()
assert cfg["station"]["callsign"] == "8P5AB" and cfg["station"]["grid"] == "GK03", cfg["station"]
assert cfg["radio"]["profile"] == "Icom IC-9100"
assert "CODEC" in cfg["radio"]["audio_device"], cfg["radio"]["audio_device"]

a.v_psk.set(True)
a.psk_toggle()
a.update_psk()
snap(a, "3-faceplate-psk-armed.png")
a.v_psk.set(False)
a.psk_toggle()

bm = g.BandsModesWindow(a)
bm.geometry("+60+40")
bm.v_slot[("2m", 9)].set(True)              # Pumpkin 144.490 on
bm.v_slot[("2m", 5)].set(False)             # FT8 off
from uranus import freqplan                 # noqa: E402
bm.v_freq[("2m", 9)][0].set(freqplan.find("2m", "pumpkin", 144.285).label())
bm.v_freq[("2m", 7)][0].set("144.489")
bm.v_freq[("2m", 4)][0].set(freqplan.find("2m", "aprs", 145.825).label())
snap(bm, "6-bands-modes.png")
assert bm.save() is True
cfg = g.load_cfg()
b2 = [b for b in cfg["band"] if b["name"] == "2m"][0]["slot"]
assert b2[9]["enabled"] is True and b2[5]["enabled"] is False
assert abs(b2[9]["freq_mhz"] - 144.285) < 1e-6 and abs(b2[7]["freq_mhz"] - 144.489) < 1e-6, b2
assert abs(b2[4]["freq_mhz"] - 145.825) < 1e-6, b2
a.v_sub.set("AUTO")
a.save_listen(mode_changed=True)
assert g.load_cfg()["receive"]["mode"] == "auto"
a.v_sub.set("FT4")
a.save_listen(mode_changed=True)
assert abs(g.load_cfg()["receive"]["dial_mhz"] - 144.170) < 1e-6
a.v_sub.set("FT8")
a.save_listen(mode_changed=True)
rx = g.load_cfg()["receive"]
assert rx["mode"] == "ft8" and abs(rx["dial_mhz"] - 144.174) < 1e-6, rx
a.evq.put({"type": "message", "mode": "FT8", "snr": -12, "text": "K1ABC W9XYZ -12", "call": "W9XYZ",
           "freq_hz": 144175500, "start": now})
a.handle_events_extra()
a.v_sub.set("CUCUMBER-15")
a.save_listen(mode_changed=True)
assert g.load_cfg()["receive"]["mode"] == "cucumber"

w = g.SetupWindow(a)
w.geometry("+60+40")
w.v["band_1.25m"].set(True)
w.v["call"].set("8P5AB")
w.v["grid"].set("GK03ec")
w.v["cat_baud"].set("19200")
w.v["band_20m"].set(True)                   # HF bands are in Station setup now
assert w.save() is True
assert g.load_cfg()["radio"]["cat_baud"] == 19200
assert [b for b in g.load_cfg()["band"] if b["name"] == "20m"][0]["active"] is True
snap(w, "4-station-setup.png")
w.destroy()
a.v_nf.set(False)
a.nf_toggle()
assert g.load_cfg()["receive"]["noise_filter"] is False
a.v_nf.set(True)
a.nf_toggle()
assert g.load_cfg()["receive"]["noise_filter"] is True
sw = g.TimetableWindow(a)
sw.geometry("+60+40")
sw.load_example()
assert sw.save() is True
tt = g.load_cfg()["timetable"]
assert tt["enabled"] is True and tt["windows"][2] == "09:03-22:00 transmit 3", tt
sw.add_row(None)
sw.rows[-1]["v"]["from"].set("23:59")
sw.rows[-1]["v"]["to"].set("24:00")
sw._preview()
snap(sw, "7-timetable.png")
sw.remove_row(sw.rows[-1])
sw.destroy()
# auto-save: change a value and let the 0.7 s timer save it without pressing anything
w2 = g.SetupWindow(a)
w2.v["max_swr"].set("2.5")
for _ in range(15):
    a.update()
    time.sleep(0.1)
assert abs(g.load_cfg()["radio"]["max_swr"] - 2.5) < 1e-9, g.load_cfg()["radio"]
w2.v["call"].set("8P")                     # half-typed: not saved, no pop-up
for _ in range(15):
    a.update()
    time.sleep(0.1)
assert g.load_cfg()["station"]["callsign"] == "8P5AB"
assert "Not saved yet" in w2.saved_lbl.cget("text"), w2.saved_lbl.cget("text")
w2.v["call"].set("8P5AB")
w2.autosave_close()
c = g.ChatWindow(a)
c.v_text.set("test")
c.estimate()
from uranus import ping as _ping   # noqa: E402
for _e in _ping.demo(seed=1):
    c.q.put(_e)
c.poll()
assert "PUMPKIN REPORT" in c.log.get("1.0", "end"), c.log.get("1.0", "end")
snap(c, "5-chat.png")
c.close()
# faceplate tools: weather fax (fed a synthetic chart), scanner, my frequencies, share
from uranus import gui_tools as T, wefax   # noqa: E402
wf = T.WefaxWindow(a)
wf.geometry("+40+30")
img = np.tile(np.linspace(0, 1, wefax.WIDTH), (60, 1))
img[:, :40] = 0
wf.rx = wefax.Receiver(outdir=os.path.join(os.environ.get("TEMP", "/tmp"), "wfx"), on_line=wf.rows.append,
                       on_event=wf._event)
x = wefax.encode(img)
for i in range(0, len(x), 1200):
    wf.rx.feed(x[i:i + 1200])
wf.tick()
assert wf.rx.saved and "Saved" in wf.status.cget("text"), wf.status.cget("text")
snap(wf, "8-weather-fax.png")
wf.rx = None
wf.destroy()
sc = T.ScannerWindow(a)
sc.geometry("+40+30")
sc.q.put({"type": "scan", "state": "dwell", "chan": "14.074 MHz FT8 (20 m)", "until": time.time() + 150})
sc.tick()
snap(sc, "9-scanner.png")
sc.destroy()
sid = T.SignalIdWindow(a)
from uranus import sigint as _si   # noqa: E402
_t = np.arange(15 * 12000) / 12000
_x = np.random.default_rng(1).normal(0, 1, len(_t)) + 1.5 * np.sin(2 * np.pi * 100 * _t)
sid.show(14.074, _si.identify(_x, dial_hz=14.074e6), -30.0)
assert "Mains hum" in sid.status.cget("text") or "Mains hum" in sid.txt.get("1.0", "end")
snap(sid, "10-signal-id.png")
sid.destroy()
mw = T.MissionWindow(a, "hurricane")
assert "NMG" in mw.changes.cget("text")
snap(mw, "11-mission.png")
mw.destroy()
assert T.apply_mission(a, "dx", open_tools=False) and g.load_cfg()["mission"]["name"] == "dx"
assert "DX HUNT" in a.mission_lbl.cget("text")
a.run_command("beacon wspr every 10 minutes overnight")
assert g.load_cfg()["timetable"]["windows"][0] == "22:00-06:00 transmit 10"
assert g.screen_layout("auto", 768) == "compact" and g.screen_layout("auto", 1080) == "full"
assert g.screen_layout("full", 768) == "full"
for W in (T.DoctorWindow, T.AccessWindow, T.FaxGallery):
    w = W(a)
    w.update()
    w.destroy()
sh = T.ShareWindow(a, "")
assert "github.com/BajanBob/Uranus/releases" in T.SHARE_TEXT
sh.destroy()
a.update()
a.destroy()
print("GUI OK")
errors = [d for d in DIALOGS if d[0] == "showerror"]
assert not errors, errors
