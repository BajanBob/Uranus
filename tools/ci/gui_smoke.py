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
assert len(a.wf_tags) == 8 and "FT8" in a.dec_last.cget("text")
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
bm.v_slot[("2m", 8)].set(True)              # Pumpkin 144.490 on
bm.v_slot[("2m", 5)].set(False)             # FT8 off
from uranus import freqplan                 # noqa: E402
bm.v_freq[("2m", 8)][0].set(freqplan.find("2m", "pumpkin", 144.285).label())
bm.v_freq[("2m", 6)][0].set("144.489")
bm.v_freq[("2m", 4)][0].set(freqplan.find("2m", "aprs", 145.825).label())
snap(bm, "6-bands-modes.png")
bm.save()
cfg = g.load_cfg()
b2 = [b for b in cfg["band"] if b["name"] == "2m"][0]["slot"]
assert b2[8]["enabled"] is True and b2[5]["enabled"] is False
assert abs(b2[8]["freq_mhz"] - 144.285) < 1e-6 and abs(b2[6]["freq_mhz"] - 144.489) < 1e-6, b2
assert abs(b2[4]["freq_mhz"] - 145.825) < 1e-6, b2
a.v_sub.set("AUTO")
a.save_listen(mode_changed=True)
assert g.load_cfg()["receive"]["mode"] == "auto"
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
assert w.save() is True
assert g.load_cfg()["radio"]["cat_baud"] == 19200
snap(w, "4-station-setup.png")
w.destroy()
c = g.ChatWindow(a)
c.v_text.set("test")
c.estimate()
snap(c, "5-chat.png")
c.close()
a.update()
a.destroy()
print("GUI OK")
errors = [d for d in DIALOGS if d[0] == "showerror"]
assert not errors, errors
