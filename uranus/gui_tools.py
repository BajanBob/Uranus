"""Faceplate tool windows: weather fax, scanner, my frequencies, screenshot and share."""
import datetime as _dt
import os
import queue
import threading
import time
import tkinter as tk
import urllib.parse
import webbrowser
from tkinter import messagebox, ttk

from . import gui as G
from . import freqplan, userfreqs

RELEASES = "https://github.com/BajanBob/Uranus/releases/latest"
SHARE_TEXT = ("Uranus: free weak-signal beacon and decoder for radio amateurs (FT8, FT4, Q65, JT65, WSPR, APRS, "
              "Pumpkin, weather fax, band scanner). Free to download and share - get it for Windows here: " + RELEASES)


def user_dir(*parts):
    d = os.path.join(os.path.expanduser("~"), "Uranus", *parts)
    os.makedirs(d, exist_ok=True)
    return d


# ===================================================================== my frequencies
class FrequencyWindow(tk.Toplevel):
    """Add your own frequencies for any band and mode; they join the dial lists, Bands and modes, the scanner
    (and, for mode WEFAX, the weather fax station list)."""

    def __init__(self, app, mode="ft8", on_change=None):
        super().__init__(app)
        self.app, self.on_change = app, on_change
        self.title("Uranus - My frequencies")
        self.geometry("760x430")
        self.configure(bg=G.C["bg"])
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Add a frequency", style="Big.TLabel").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(8, 4))
        ttk.Label(row, text="Mode").pack(side="left")
        self.v_mode = tk.StringVar(value=mode.upper())
        cb = ttk.Combobox(row, textvariable=self.v_mode, values=[m.upper() for m in userfreqs.MODES],
                          state="readonly", width=9)
        cb.pack(side="left", padx=(4, 12))
        ttk.Label(row, text="MHz").pack(side="left")
        self.v_mhz = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.v_mhz, width=12)
        e.pack(side="left", padx=(4, 12))
        G.Tooltip(e, "Dial frequency in MHz, e.g. 14.074 or 144.174. For WEFAX give the published (assigned) "
                     "frequency, e.g. 4.3179; Uranus tunes 1.9 kHz lower on USB.")
        ttk.Label(row, text="Note").pack(side="left")
        self.v_note = tk.StringVar()
        ttk.Entry(row, textvariable=self.v_note, width=22).pack(side="left", padx=(4, 8))
        ttk.Button(row, text="Add", command=self.add).pack(side="left")
        self.msg = tk.Label(f, text="", bg=G.C["bg"], fg=G.C["amber"], font=(G.UI, 10), anchor="w")
        self.msg.pack(fill="x")
        ttk.Label(f, text="Your frequencies", style="CardMuted.TLabel").pack(anchor="w", pady=(10, 2))
        self.lb = tk.Listbox(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), height=12,
                             selectbackground=G.C["blue"], highlightthickness=0)
        self.lb.pack(fill="both", expand=True)
        ttk.Button(f, text="Remove selected", command=self.remove).pack(anchor="w", pady=(6, 0))
        self.refresh()

    def refresh(self):
        self.items = userfreqs.load(G.CONFIG)
        self.lb.delete(0, "end")
        for i in self.items:
            band = freqplan.BAND_NAMES.get(i.get("band", ""), "HF")
            self.lb.insert("end", f"{freqplan.fmt(float(i['mhz'])):>10} MHz  {i['mode'].upper():<8}{band:<8}"
                                  f"{i.get('note', '')}")

    def add(self):
        try:
            mhz = float(self.v_mhz.get().replace(",", "."))
        except ValueError:
            self.msg.config(text="Type the frequency in MHz, e.g. 14.074.")
            return
        why = userfreqs.add(G.CONFIG, self.v_mode.get().lower(), mhz, self.v_note.get())
        self.msg.config(text=why or f"Added {freqplan.fmt(mhz)} MHz {self.v_mode.get()}.",
                        fg=G.C["red"] if why else G.C["green"])
        if not why:
            self.v_mhz.set("")
            self.v_note.set("")
            self.refresh()
            if self.on_change:
                self.on_change()

    def remove(self):
        sel = self.lb.curselection()
        if not sel:
            return
        i = self.items[sel[0]]
        userfreqs.remove(G.CONFIG, i["mode"], float(i["mhz"]))
        self.refresh()
        if self.on_change:
            self.on_change()


# ===================================================================== weather fax
class WefaxWindow(tk.Toplevel):
    """HF weather fax: pick a station (or your own frequency), tune by CAT, and charts build up line by line.
    Each chart is saved as a PNG when its stop tone arrives."""

    VIEW_W = 905                       # half the 1809-pixel line

    def __init__(self, app):
        super().__init__(app)
        from . import wefax
        self.app, self.wefax = app, wefax
        self.title("Uranus - Weather fax (HF WEFAX)")
        self.geometry("980x760")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        self.rx = self.audio = None
        self.rows = []
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Station").pack(side="left")
        self.v_st = tk.StringVar()
        self.cb = ttk.Combobox(top, textvariable=self.v_st, state="readonly", width=62, font=(G.MONO, 9))
        self.cb.pack(side="left", padx=(4, 8))
        self.cb.bind("<<ComboboxSelected>>", lambda e: self.show_dial())
        G.Tooltip(self.cb, "Published (assigned) frequencies. Uranus tunes the radio to USB 1.9 kHz lower, so "
                           "the fax subcarrier lands at 1900 Hz. From Barbados and the Caribbean, New Orleans "
                           "(NMG) and Boston (NMF) are the strongest: try 8503.9 or 12789.9 kHz by day, "
                           "4317.9 or 6340.5 kHz at night.")
        ttk.Button(top, text="My frequencies...", command=lambda: FrequencyWindow(
            self.app, "wefax", on_change=self.load_stations)).pack(side="left")
        self.dial = tk.Label(self, text="", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 10), anchor="w", padx=10)
        self.dial.pack(fill="x")
        ctl = ttk.Frame(self, padding=(10, 4))
        ctl.pack(fill="x")
        self.b_start = ttk.Button(ctl, text="Tune and receive", command=self.start)
        self.b_start.pack(side="left")
        G.Tooltip(self.b_start, "Tune the radio (CAT) to the station, then wait for a chart's start tone. "
                                "Charts start by themselves; most stations send one every 10-20 minutes.")
        b = ttk.Button(ctl, text="Start chart now", command=self.start_now)
        b.pack(side="left", padx=6)
        G.Tooltip(b, "Begin a picture immediately, to join a chart already in progress (its left edge may be "
                     "off because the phasing lines were missed).")
        ttk.Button(ctl, text="Save now", command=self.save_now).pack(side="left")
        ttk.Button(ctl, text="Stop", command=self.stop).pack(side="left", padx=6)
        ttk.Button(ctl, text="Gallery", command=lambda: FaxGallery(self.app)).pack(side="left")
        self.v_auto = tk.BooleanVar(value=bool(G.load_cfg().get("wefax", {}).get("autopilot", False)))
        ac = ttk.Checkbutton(ctl, text="Autopilot", variable=self.v_auto)
        ac.pack(side="left", padx=(10, 0))
        G.Tooltip(ac, "Autopilot: picks the station's day (10-22 MHz) or night (3-10 MHz) frequency from the sun at "
                      "your location, moves to its next frequency if no chart starts within 25 minutes, and "
                      "re-picks at sunrise and sunset.")
        ttk.Label(ctl, text="Slant (ppm)").pack(side="left", padx=(16, 4))
        self.v_ppm = tk.StringVar(value=str(G.load_cfg().get("wefax", {}).get("ppm", 0)))
        sp = ttk.Spinbox(ctl, from_=-500, to=500, increment=5, textvariable=self.v_ppm, width=6)
        sp.pack(side="left")
        G.Tooltip(sp, "If charts come out slanted, your sound card clock is off. Lines leaning to the right: "
                      "make this more negative; leaning left: more positive. Typical values are -100 to +100.")
        self.status = tk.Label(self, text="Choose a station, then press Tune and receive.", bg=G.C["bg"],
                               fg=G.C["ink"], font=(G.UI, 11, "bold"), anchor="w", padx=10)
        self.status.pack(fill="x", pady=(4, 2))
        self.cv = tk.Canvas(self, bg="#ffffff", highlightthickness=0, width=self.VIEW_W, height=560)
        self.cv.pack(padx=10, pady=(0, 10), anchor="w")
        self.img_item = self.cv.create_image(0, 0, anchor="nw")
        self.load_stations()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(500, self.tick)

    def load_stations(self):
        self.stations = list(self.wefax.STATIONS)
        for i in userfreqs.load(G.CONFIG):
            if i["mode"] == "wefax":
                self.stations.insert(0, ("My frequency", "MINE", float(i["mhz"]) * 1000, i.get("note") or "added by you"))
        self.cb.config(values=[self.wefax.station_label(s) for s in self.stations])
        if not self.v_st.get():
            want = G.load_cfg().get("wefax", {}).get("station", "NMG")
            from .bandadvisor import sun_elevation
            st = G.load_cfg().get("station", {})
            day = sun_elevation(float(st.get("lat", 13.1)), float(st.get("lon", -59.6))) > 0
            khz = self.wefax.pick(want, day) or 8503.9
            self.cb.current(next((k for k, s in enumerate(self.stations) if s[1] == want and s[2] == khz), 0))
        self.show_dial()

    def station(self):
        return self.stations[max(0, self.cb.current())]

    def show_dial(self):
        st = self.station()
        self.dial.config(text=f"{st[1]} {st[0]}: assigned {st[2]:.1f} kHz  ->  radio USB dial "
                              f"{self.wefax.dial_mhz(st[2]):.4f} MHz · 120 LPM, IOC 576")

    # -- receiving
    def start(self):
        if self.app.worker or self.app.runner:
            messagebox.showinfo("Weather fax", "Stop Listen + decode, ON AIR or the scanner first: the fax "
                                               "receiver needs the radio and its audio to itself.", parent=self)
            return
        self.stop()
        try:
            ppm = float(self.v_ppm.get())
        except ValueError:
            ppm = 0.0
        G.write_keys({("wefax", "ppm"): ppm})
        cfg = G.load_cfg()
        st = self.station()
        dial = self.wefax.dial_mhz(st[2])

        def go():
            from . import tuning
            try:
                self.q.put(("note", tuning.tune(cfg, dial, "USB")))
            except Exception as e:                  # noqa: BLE001
                self.q.put(("note", f"Could not tune the radio ({e}); set USB {dial:.4f} MHz by hand."))
        threading.Thread(target=go, daemon=True).start()
        self.rows = []
        self.rx = self.wefax.Receiver(ppm=ppm, outdir=user_dir("wefax"), label=f"{st[1]}_{st[2]:.0f}kHz",
                                      on_line=self.rows.append, on_event=self._event)
        from .tuning import AudioIn
        dev = cfg.get("receive", {}).get("audio_device", "default")
        self.audio = AudioIn(dev, self.rx.feed)
        try:
            self.audio.start()
        except Exception as e:                      # noqa: BLE001
            self.audio = None
            self.status.config(text=f"No receive audio: {e}", fg=G.C["red"])
            return
        self.app.wefax_on = True
        self.listen_since = time.time()
        self.daytime = self._daytime()
        self.status.config(text=f"Listening on {st[1]} {st[2]:.1f} kHz · waiting for a start tone...",
                           fg=G.C["purple"])
        self.app.print(f"\n> weather fax: {st[1]} {st[2]:.1f} kHz (USB dial {dial:.4f} MHz)\n")

    def _event(self, e):
        if e["type"] == "start":                     # audio thread: a new chart starts on a clean view
            self.rows.clear()
        self.q.put(("event", e))

    def start_now(self):
        if not self.rx:
            self.start()
        if self.rx:
            self.rx.start_now()

    def save_now(self):
        if self.rx:
            path = self.rx.finish()
            if not path:
                self.status.config(text="Nothing to save yet (fewer than 20 lines).", fg=G.C["muted"])

    def stop(self):
        if self.audio:
            self.audio.stop()
            self.audio = None
        if self.rx and self.rx.state == "image":
            self.rx.finish()
        self.rx = None
        self.app.wefax_on = False

    def close(self):
        self.stop()
        self.destroy()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, e = self.q.get_nowait()
                if kind == "note":
                    self.app.print(e + "\n")
                elif e["type"] == "start_tone":
                    self.status.config(text="Start tone heard · phasing...", fg=G.C["decode"])
                elif e["type"] == "start":
                    self.status.config(text="Receiving a chart...", fg=G.C["decode"])
                elif e["type"] == "saved":
                    self.status.config(text=f"Saved {os.path.basename(e['path'])} ({e['lines']} lines). Waiting "
                                            "for the next chart...", fg=G.C["green"])
                    self.app.print(f"Weather fax saved: {e['path']}\n")
                    self.app.add_ticker(f"WEFAX chart saved: {os.path.basename(e['path'])}", log=False)
                    from . import speech
                    speech.say("Weather chart received")
        except queue.Empty:
            pass
        if self.rx and self.v_auto.get():
            self._autopilot()
        if self.rx and self.rx.state == "image":
            self.status.config(text=f"Receiving a chart · {len(self.rx.lines)} lines "
                                    f"({len(self.rx.lines) / 120:.1f} min)", fg=G.C["decode"])
        self.draw()
        self.after(1000, self.tick)

    def _daytime(self):
        from .bandadvisor import sun_elevation
        st = G.load_cfg().get("station", {})
        return sun_elevation(float(st.get("lat", 13.1)), float(st.get("lon", -59.6))) > 0

    def _select(self, call, khz):
        k = next((i for i, s in enumerate(self.stations) if s[1] == call and abs(s[2] - khz) < 0.05), None)
        if k is not None:
            self.cb.current(k)
            self.show_dial()

    def _autopilot(self):
        """Hop to the station's next channel when nothing starts for 25 minutes; re-pick at sunrise / sunset."""
        if self.rx.state != "idle":
            self.listen_since = time.time()
            return
        st = self.station()
        day = self._daytime()
        target = None
        if day != getattr(self, "daytime", day):
            target, why = self.wefax.pick(st[1], day), "sunrise" if day else "sunset"
        elif time.time() - getattr(self, "listen_since", time.time()) > 25 * 60:
            target, why = self.wefax.next_frequency(st[1], st[2]), "no chart for 25 minutes"
        if target and abs(target - st[2]) > 0.05:
            self.app.print(f"Weather fax autopilot: {why}, moving {st[1]} to {target:.1f} kHz\n")
            self._select(st[1], target)
            self.start()
        elif target:
            self.listen_since, self.daytime = time.time(), day

    def draw(self):
        import numpy as np
        if not self.rows:
            return
        h = int(self.cv.cget("height"))
        rows = np.roll(np.array(self.rows[-2 * h:]), -int((self.rx.phase if self.rx else 0) or 0), axis=1)
        img = (np.clip(rows[:, ::2][:, :self.VIEW_W], 0, 1) * 255).astype(np.uint8)
        img = img[::2] if len(img) > h else img                 # two lines per screen row when full
        rgb = np.repeat(img[:, :, None], 3, axis=2)
        ppm = b"P6 %d %d 255\n" % (rgb.shape[1], rgb.shape[0]) + rgb.tobytes()
        try:
            self.photo = tk.PhotoImage(data=ppm, format="PPM")
        except tk.TclError:
            import base64
            self.photo = tk.PhotoImage(data=base64.b64encode(ppm), format="PPM")
        self.cv.itemconfig(self.img_item, image=self.photo)


# ===================================================================== scanner
class ScannerWindow(tk.Toplevel):
    """Choose bands and modes, then scan: the radio steps through every known (and your own) frequency and
    stops where it hears something, for up to 3 minutes or until the transmissions stop."""

    MODES = ("ft8", "ft4", "q65", "jt65", "jt9", "fst4w", "wspr", "aprs", "pumpkin", "ur", "cucumber")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Scanner")
        self.geometry("780x600")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        self.sc = None
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Scan known frequencies", style="Big.TLabel").pack(anchor="w")
        ttk.Label(f, text="Bands", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 0))
        bf = ttk.Frame(f)
        bf.pack(fill="x")
        try:
            dial = float(app.v_dial.get().split()[0])
        except (ValueError, AttributeError, IndexError):
            dial = 14.074
        here = userfreqs.band_of(dial) or "20m"
        pre = G.load_cfg().get("scanner", {})
        self.v_band = {}
        for k, b in enumerate(freqplan.BAND_EDGES):
            self.v_band[b] = tk.BooleanVar(value=b in pre.get("bands", [here]))
            ttk.Checkbutton(bf, text=freqplan.BAND_NAMES[b], variable=self.v_band[b]).grid(
                row=k // 7, column=k % 7, sticky="w", padx=(0, 10))
        ttk.Label(f, text="Modes", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 0))
        mf = ttk.Frame(f)
        mf.pack(fill="x")
        self.v_mode = {}
        for k, m in enumerate(self.MODES):
            self.v_mode[m] = tk.BooleanVar(value=m in pre.get("modes", ("ft8", "ft4", "jt65", "q65", "wspr")))
            ttk.Checkbutton(mf, text=m.upper(), variable=self.v_mode[m]).grid(row=k // 6, column=k % 6, sticky="w",
                                                                              padx=(0, 10))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Stop on a signal for up to").pack(side="left")
        self.v_dwell = tk.StringVar(value=str(pre.get("dwell_min", 3)))
        ttk.Spinbox(row, from_=1, to=30, textvariable=self.v_dwell, width=4).pack(side="left", padx=4)
        ttk.Label(row, text="minutes, or until it goes quiet").pack(side="left")
        ttk.Button(row, text="My frequencies...", command=lambda: FrequencyWindow(self.app)).pack(side="right")
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", pady=(10, 0))
        ttk.Button(ctl, text="Start scan", command=self.start).pack(side="left")
        b = ttk.Button(ctl, text="Continue", command=lambda: self.sc and self.sc.cont())
        b.pack(side="left", padx=6)
        G.Tooltip(b, "Leave this channel now and go on to the next.")
        b = ttk.Button(ctl, text="Ignore", command=lambda: self.sc and self.sc.ignore())
        b.pack(side="left")
        G.Tooltip(b, "Leave this channel and skip it for the rest of the scan (e.g. a local noise source).")
        ttk.Button(ctl, text="Stop", command=self.stop).pack(side="left", padx=6)
        self.status = tk.Label(f, text="Tick the bands and modes, then Start scan. Needs CAT control of the radio.",
                               bg=G.C["bg"], fg=G.C["ink"], font=(G.UI, 11, "bold"), anchor="w")
        self.status.pack(fill="x", pady=(10, 4))
        self.log = tk.Listbox(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), height=14,
                              highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(500, self.tick)

    def start(self):
        from . import scanner
        if self.app.worker or getattr(self.app, "wefax_on", False):
            messagebox.showinfo("Scanner", "Press Stop first (Listen + decode, ON AIR or weather fax is running).",
                                parent=self)
            return
        bands = {b for b, v in self.v_band.items() if v.get()}
        modes = {m for m, v in self.v_mode.items() if v.get()}
        chans = scanner.channels(bands, modes)
        if not chans:
            self.status.config(text="No known frequencies for those bands and modes.", fg=G.C["amber"])
            return
        try:
            dwell = max(1.0, float(self.v_dwell.get())) * 60
        except ValueError:
            dwell = scanner.DWELL_S
        cfg = G.load_cfg()
        if cfg.get("radio", {}).get("backend") != "hamlib":
            if not messagebox.askyesno("Scanner", "The radio is not under CAT control, so Uranus cannot change "
                                                  "frequency. Scan anyway (you tune by hand)?", parent=self):
                return
        self.log.delete(0, "end")
        self.log.insert("end", f"{len(chans)} channels: " + ", ".join(c.label() for c in chans[:6])
                        + (" ..." if len(chans) > 6 else ""))

        def ev(e):
            if e["type"] == "scan":
                self.q.put(e)
            self.app.on_listen_event(e)
        if self.app.v_psk.get():
            self.app.reporter = self.app._make_reporter()
        self.sc = scanner.Scanner(cfg, chans, self.app.reporter, on_event=ev, dwell_s=dwell)

        def go():
            self.app.runner = self.sc
            self.sc.run()
        self.app.print(f"\n> scanner: {len(chans)} channels, dwell up to {dwell / 60:.0f} min\n")
        self.app.start(go, "Scanning. Press Stop to end.", "listen")

    def stop(self):
        if self.sc:
            self.sc.halt()

    def close(self):
        self.stop()
        self.destroy()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                e = self.q.get_nowait()
                st, ch, t = e["state"], e["chan"], time.strftime("%H:%M:%S")
                text = {"probe": f"Listening on {ch}", "quiet": f"{ch}: quiet",
                        "dwell": f"Signal on {ch}: staying (Continue / Ignore to move on)",
                        "ended": f"{ch}: moving on ({e.get('reason', '')})", "ignored": f"{ch}: ignored",
                        "stopped": "Scan stopped", "done": f"Scan ended: {e.get('reason', '')}"}.get(st, st)
                if st == "probe" and e.get("note"):
                    text += f" · {e['note']}"
                self.log.insert("end", f"{t}  {text}")
                self.log.see("end")
                self.status.config(text=text, fg=G.C["green"] if st == "dwell" else G.C["ink"])
                self.dwell_until = e.get("until") if st == "dwell" else None
        except queue.Empty:
            pass
        until = getattr(self, "dwell_until", None)
        if until and self.sc and self.sc.current:
            left = max(0, int(until - time.time()))
            self.status.config(text=f"Signal on {self.sc.current.label()} · staying {left // 60}:{left % 60:02d} "
                                    "more (Continue / Ignore to move on)", fg=G.C["green"])
        self.after(1000, self.tick)


# ===================================================================== screenshot and share
def screenshot(app):
    """Save a PNG of the Uranus window. Returns the path, or raises with a reason."""
    app.update_idletasks()
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    from PIL import ImageGrab
    try:
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    except TypeError:
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    path = os.path.join(user_dir("screenshots"), f"uranus_{_dt.datetime.now():%Y%m%d_%H%M%S}.png")
    img.save(path)
    return path


def share_whatsapp(text=SHARE_TEXT):
    webbrowser.open("https://wa.me/?text=" + urllib.parse.quote(text))


def share_email(text=SHARE_TEXT, attachment=""):
    body = text + ("\n\nScreenshot attached." if attachment else "")
    webbrowser.open("mailto:?subject=" + urllib.parse.quote("Uranus - free weak-signal software for radio amateurs")
                    + "&body=" + urllib.parse.quote(body))


class ShareWindow(tk.Toplevel):
    """Share Uranus (free to share) by WhatsApp or email, with an optional screenshot of the current screen."""

    def __init__(self, app, shot=""):
        super().__init__(app)
        self.app, self.shot = app, shot
        self.title("Uranus - Share")
        self.geometry("780x330")
        self.configure(bg=G.C["bg"])
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Share Uranus", style="Big.TLabel").pack(anchor="w")
        tk.Label(f, text=SHARE_TEXT, bg=G.C["bg"], fg=G.C["ink"], font=(G.UI, 10), wraplength=740,
                 justify="left").pack(anchor="w", pady=(6, 8))
        self.shot_lbl = tk.Label(f, text="", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9), wraplength=740,
                                 justify="left")
        self.shot_lbl.pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Button(row, text="WhatsApp", command=self.whatsapp).pack(side="left")
        ttk.Button(row, text="Email", command=self.email).pack(side="left", padx=6)
        ttk.Button(row, text="Copy link", command=self.copy).pack(side="left")
        ttk.Button(row, text="Take screenshot", command=self.take).pack(side="left", padx=6)
        self.open_btn = ttk.Button(row, text="Show screenshot", command=lambda: self.shot and G._open(self.shot))
        self.open_btn.pack(side="left")
        tk.Label(f, text="WhatsApp and email open with the message and download link filled in. A web link "
                         "cannot attach files, so to send the screenshot too, attach it from the folder that "
                         "opens (or drag it into the chat).", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9),
                 wraplength=740, justify="left").pack(anchor="w", pady=(12, 0))
        self.show_shot()

    def show_shot(self):
        self.shot_lbl.config(text=f"Screenshot: {self.shot}" if self.shot else "No screenshot yet.")

    def take(self):
        self.withdraw()
        self.app.after(300, self._take)

    def _take(self):
        try:
            self.shot = screenshot(self.app)
        except Exception as e:                      # noqa: BLE001
            messagebox.showerror("Screenshot", f"Could not capture the screen: {e}", parent=self.app)
        self.deiconify()
        self.show_shot()

    def _reveal(self):
        if self.shot:
            G._open(os.path.dirname(self.shot))

    def whatsapp(self):
        share_whatsapp()
        self._reveal()

    def email(self):
        share_email(attachment=self.shot)
        self._reveal()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(SHARE_TEXT)
        self.shot_lbl.config(text="Message and link copied: paste them anywhere.")


# ===================================================================== signal ID
class SignalIdWindow(tk.Toplevel):
    """'What is this I'm hearing?': record the receiver for 15 seconds and name everything in the passband,
    with what it is, what it sounds like, what to do next, and known users of the dial frequency."""

    SECONDS = 15

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Signal ID")
        self.geometry("860x620")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        self.busy, self.top, self.dial = False, None, 0.0
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Signal ID - what is this I'm hearing?", style="Big.TLabel").pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(8, 4))
        ttk.Label(row, text="Dial MHz").pack(side="left")
        self.v_dial = tk.StringVar(value=(app.v_dial.get().split() or ["14.074"])[0])
        ttk.Entry(row, textvariable=self.v_dial, width=10).pack(side="left", padx=(4, 10))
        b = ttk.Button(row, text=f"Identify ({self.SECONDS} s)", command=self.identify)
        b.pack(side="left")
        G.Tooltip(b, "Records the radio's receive audio for 15 seconds and names every signal and every kind of "
                     "interference in it: FT8 and friends, CW, RTTY, NAVTEX, weather fax, ALE, voice, carriers, "
                     "mains hum, charger noise and clicks.")
        self.v_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Keep identifying", variable=self.v_keep).pack(side="left", padx=10)
        self.b_more = ttk.Button(row, text="Read more", command=self.read_more)
        self.b_more.pack(side="left")
        self.b_go = ttk.Button(row, text="", command=self.go_action)
        teach = ttk.Frame(f)
        teach.pack(fill="x", pady=(4, 0))
        ttk.Label(teach, text="Teach Uranus:").pack(side="left")
        b = ttk.Button(teach, text="Right", command=lambda: self.teach(True))
        b.pack(side="left", padx=(6, 4))
        G.Tooltip(b, "The top answer is right: remember it for this frequency. Next time it gains confidence, and "
                     "anything new on this frequency is flagged.")
        ttk.Button(teach, text="Wrong, it is:", command=lambda: self.teach(False)).pack(side="left")
        from . import sigint as _si
        self.v_actual = tk.StringVar(value="")
        ttk.Combobox(teach, textvariable=self.v_actual, values=sorted(_si.INFO), width=24).pack(side="left", padx=4)
        self.usual = tk.Label(teach, text="", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9), anchor="w")
        self.usual.pack(side="left", padx=8)
        self.status = tk.Label(f, text="Tune the radio to the signal, then press Identify.", bg=G.C["bg"],
                               fg=G.C["ink"], font=(G.UI, 11, "bold"), anchor="w")
        self.status.pack(fill="x", pady=(6, 4))
        self.txt = tk.Text(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), wrap="word", height=24,
                           highlightthickness=0, padx=8, pady=6)
        self.txt.tag_config("name", foreground=G.C["green"], font=(G.MONO, 11, "bold"))
        self.txt.tag_config("noise", foreground=G.C["amber"], font=(G.MONO, 11, "bold"))
        self.txt.tag_config("ctx", foreground=G.C["muted"])
        self.txt.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(300, self.tick)

    def identify(self):
        if self.busy:
            return
        try:
            dial = float(self.v_dial.get().replace(",", "."))
        except ValueError:
            dial = 0.0
        self.busy = True
        self.status.config(text=f"Listening for {self.SECONDS} seconds...", fg=G.C["purple"])
        dev = G.load_cfg().get("receive", {}).get("audio_device", "default")
        import numpy as np

        def work():
            from . import monitor, sigint
            try:
                t0 = time.time()
                x = monitor.record(self.SECONDS, dev)
                self.q.put(("ok", dial, sigint.identify(x, dial_hz=dial * 1e6, t0=t0),
                            float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))))
            except Exception as e:                  # noqa: BLE001
                self.q.put(("err", str(e), None, None))
        threading.Thread(target=work, daemon=True).start()

    def teach(self, right):
        from . import siglib
        if not self.top or not self.dial:
            return
        actual = self.v_actual.get().strip() or None
        siglib.teach(self.dial, self.top, right, actual)
        self.status.config(text=("Learned: " + self.top.name if right else
                                 f"Noted: not {self.top.name}" + (f", it is {actual}" if actual else "")) +
                           f" on {self.dial:.4f} MHz", fg=G.C["green"])
        self._usual()

    def _usual(self):
        from . import siglib
        u = siglib.usual(self.dial) if self.dial else []
        self.usual.config(text=("Usual here: " + ", ".join(f"{n} ×{c}" for n, c in u[:4])) if u else "")

    def show(self, dial, found, level_db):
        from . import sigint, siglib
        self.dial = dial
        if dial:
            found = siglib.annotate(found, dial)
        self._usual()
        new = [f for f in found if getattr(f, "new_here", False)]
        if new:
            self.app.add_ticker(f"SIGNAL ID: NEW on {dial:.4f} MHz: {new[0].name}", alert=True)
            from . import speech
            speech.say(f"New signal on {dial:.3f} megahertz: {new[0].name}")
        self.txt.delete("1.0", "end")
        if dial:
            self.txt.insert("end", f"Dial {dial:.4f} MHz: " + "; ".join(sigint.context(dial)) + "\n", "ctx")
        self.txt.insert("end", f"Audio level {level_db:.0f} dBFS" + (" - very low: raise the radio's USB audio "
                                                                      "or the Windows input level" if level_db < -50
                                                                      else "") + "\n\n", "ctx")
        for f in found:
            at = f" at {f.freq_hz:.0f} Hz" if f.freq_hz else ""
            flag = "  NEW HERE" if getattr(f, "new_here", False) else ""
            self.txt.insert("end", f"{f.name}{at}  {f.confidence:.0%}{flag}\n", "noise" if f.kind != "signal" else "name")
            for label, val in (("What", f.what), ("Sounds like", f.sounds), ("Why", "; ".join(f.reasons[:3])),
                               ("Next", f.action)):
                if val:
                    self.txt.insert("end", f"  {label}: {val}\n")
            self.txt.insert("end", "\n")
        self.top = found[0] if found else None
        sig = [f for f in found if f.kind == "signal" and f.name != "Noise only"]
        head = sig[0] if sig else (found[0] if found else None)
        self.status.config(text=(f"Most likely: {head.name} ({head.confidence:.0%})" if head else
                                 "Nothing recognised"), fg=G.C["green"] if sig else G.C["amber"])
        act = {"WEFAX": "Open Weather fax"}.get(head.name if head else "")
        if head and head.name in ("FT8", "FT4", "WSPR", "Q65", "JT65"):
            act = f"Decode {head.name}"
        if act:
            self.b_go.config(text=act)
            self.b_go.pack(side="left", padx=6, in_=self.b_more.master)
            self.act = (act, head.name)
        else:
            self.b_go.pack_forget()
        if head:
            self.app.add_ticker(f"SIGNAL ID: {head.name} ({head.confidence:.0%})", log=False)

    def read_more(self):
        if self.top and self.top.link:
            webbrowser.open(self.top.link)
        else:
            webbrowser.open("https://www.sigidwiki.com/wiki/Database")

    def go_action(self):
        act, name = getattr(self, "act", ("", ""))
        if name == "WEFAX":
            WefaxWindow(self.app)
        elif act.startswith("Decode"):
            self.app.v_sub.set(name)
            self.app.v_dial.set(self.v_dial.get())
            self.app.save_listen(mode_changed=False)
            self.app.print(f"Decode set to {name} on {self.v_dial.get()} MHz: press Listen + decode.\n")

    def close(self):
        self.v_keep.set(False)
        self.destroy()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, a, found, lvl = self.q.get_nowait()
                self.busy = False
                if kind == "err":
                    self.status.config(text=f"No receive audio: {a}", fg=G.C["red"])
                else:
                    self.show(a, found, lvl)
                    if self.v_keep.get():
                        self.after(500, self.identify)
        except queue.Empty:
            pass
        self.after(300, self.tick)


# ===================================================================== mission profiles
class MissionWindow(tk.Toplevel):
    """Pick a mission: one click sets the decoder, timetable and tools for the job."""

    def __init__(self, app, preselect=None):
        super().__init__(app)
        from . import profiles
        self.app, self.profiles = app, profiles
        self.title("Uranus - Mission")
        self.geometry("900x620")
        self.configure(bg=G.C["bg"])
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Choose a mission", style="Big.TLabel").pack(anchor="w")
        cur = profiles.current(G.load_cfg())
        tk.Label(f, text=f"Now: {cur.name}" if cur else "Now: your own settings", bg=G.C["bg"], fg=G.C["muted"],
                 font=(G.UI, 10)).pack(anchor="w", pady=(2, 8))
        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y")
        self.v = tk.StringVar(value=(preselect or (cur.key if cur else profiles.MISSIONS[0].key)))
        for m in profiles.MISSIONS:
            rb = ttk.Radiobutton(left, text=m.name, value=m.key, variable=self.v, command=self.show)
            rb.pack(anchor="w", pady=4)
        right = ttk.Frame(body, padding=(18, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)
        self.title_lbl = tk.Label(right, text="", bg=G.C["bg"], fg=G.C["ink"], font=(G.UI, 15, "bold"), anchor="w")
        self.title_lbl.pack(fill="x")
        self.summary = tk.Label(right, text="", bg=G.C["bg"], fg=G.C["ink"], font=(G.UI, 10), wraplength=560,
                                justify="left", anchor="w")
        self.summary.pack(fill="x", pady=(4, 8))
        ttk.Label(right, text="Apply changes:", style="CardMuted.TLabel").pack(anchor="w")
        self.changes = tk.Label(right, text="", bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), wraplength=560,
                                justify="left", anchor="nw", padx=10, pady=8)
        self.changes.pack(fill="x")
        self.tips = tk.Label(right, text="", bg=G.C["bg"], fg=G.C["amber"], font=(G.UI, 9), wraplength=560,
                             justify="left", anchor="w")
        self.tips.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        self.v_open = tk.BooleanVar(value=True)
        ttk.Checkbutton(row, text="Open the mission's tools", variable=self.v_open).pack(side="left")
        ttk.Button(row, text="Apply mission", command=self.apply).pack(side="right")
        self.show()

    def show(self):
        m = self.profiles.BY_KEY[self.v.get()]
        self.title_lbl.config(text=m.name)
        self.summary.config(text=m.summary)
        self.changes.config(text="\n".join("• " + c for c in m.changes()))
        self.tips.config(text="\n".join(m.tips))

    def apply(self):
        apply_mission(self.app, self.v.get(), open_tools=self.v_open.get())
        self.destroy()


def apply_mission(app, key, open_tools=True):
    from . import profiles, speech
    m = profiles.BY_KEY[key]
    if app.worker:
        messagebox.showinfo("Mission", "Press Stop first: the mission changes the decoder and timetable.")
        return False
    err = G.write_keys(profiles.config_changes(m))
    if err:
        messagebox.showerror("Mission", err)
        return False
    speech.ENABLED = bool(m.extras.get("speak", speech.ENABLED))
    app.refresh_station()
    if hasattr(app, "mission_lbl"):
        app.mission_lbl.config(text=f"MISSION · {m.name.upper()}")
    app.print(f"\n> mission: {m.name}\n" + "\n".join("  " + c for c in m.changes()) + "\n")
    app.add_ticker(f"MISSION: {m.name}", log=False)
    speech.say(f"Mission: {m.name}")
    if open_tools:
        opener = {"wefax": lambda: WefaxWindow(app), "scanner": lambda: ScannerWindow(app),
                  "signal_id": lambda: SignalIdWindow(app), "chat": app.chat, "map": app.station_map,
                  "best": lambda: BestBandWindow(app), "health": lambda: HealthWindow(app)}
        for t in m.tools:
            try:
                opener[t]()
            except Exception as e:                  # noqa: BLE001
                app.print(f"Could not open {t}: {e}\n")
    return True


# ===================================================================== best band now
class BestBandWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Best band now")
        self.geometry("820x560")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Best band now", style="Big.TLabel").pack(anchor="w")
        self.head = tk.Label(f, text="Working it out...", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 10),
                             wraplength=780, justify="left", anchor="w")
        self.head.pack(fill="x", pady=(4, 8))
        self.lb = tk.Listbox(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 11), height=12,
                             selectbackground=G.C["blue"], highlightthickness=0)
        self.lb.pack(fill="both", expand=True)
        self.why = tk.Label(f, text="", bg=G.C["bg"], fg=G.C["ink"], font=(G.UI, 10), wraplength=780,
                            justify="left", anchor="w")
        self.why.pack(fill="x", pady=(6, 0))
        self.lb.bind("<<ListboxSelect>>", lambda e: self.explain())
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(8, 0))
        ttk.Button(row, text="Go there", command=self.go).pack(side="left")
        ttk.Button(row, text="Refresh", command=self.refresh).pack(side="left", padx=6)
        tk.Label(row, text="Rough guide from your own decodes, PSK Reporter and the sun (NOAA SWPC); not a forecast.",
                 bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9)).pack(side="left", padx=10)
        self.res = None
        self.refresh()
        self.after(300, self.tick)

    def refresh(self):
        self.head.config(text="Working it out...")
        cfg = G.load_cfg()

        def work():
            from . import bandadvisor, pskreporter
            st = cfg["station"]
            heard = []
            try:
                if st.get("callsign", "N0CALL") != "N0CALL":
                    heard = pskreporter.heard_by(st["callsign"], 3600,
                                                 cfg.get("reporting", {}).get("pskreporter_contact") or None)
            except Exception:                       # noqa: BLE001
                heard = []
            try:
                self.q.put(bandadvisor.advise(st.get("grid6") or st["grid"], heard=heard))
            except Exception as e:                  # noqa: BLE001
                self.q.put({"error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            res = self.q.get_nowait()
            if "error" in res:
                self.head.config(text=f"Could not work it out: {res['error']}")
            else:
                self.res = res
                self.head.config(text=f"Sun {res['sun_elevation']:+.0f}° here · solar flux {res['sfi']:.0f} · "
                                      f"Kp {res['kp']:.0f} ({res['solar_source']}) · rough MUF {res['muf']} MHz")
                self.lb.delete(0, "end")
                for r in res["ranked"]:
                    bar = "█" * int(r["score"] * 20)
                    self.lb.insert("end", f"{freqplan.BAND_NAMES.get(r['band'], r['band']):>6}  {r['mode']} "
                                          f"{freqplan.fmt(r['dial_mhz']):>9}  {bar:<20} {r['score']:.0%}"
                                          + ("  heard" if r["heard_here"] else ""))
                self.lb.selection_set(0)
                self.explain()
                from . import speech
                top = res["ranked"][0]
                speech.say(f"Best band now: {freqplan.BAND_NAMES.get(top['band'], top['band'])}")
        except queue.Empty:
            pass
        self.after(300, self.tick)

    def explain(self):
        sel = self.lb.curselection()
        if self.res and sel:
            r = self.res["ranked"][sel[0]]
            self.why.config(text="Why: " + "; ".join(r["reasons"]))

    def go(self):
        sel = self.lb.curselection()
        if not (self.res and sel):
            return
        r = self.res["ranked"][sel[0]]
        self.app.v_sub.set("AUTO")
        self.app.v_dial.set(freqplan.fmt(r["dial_mhz"]))
        self.app.save_listen(mode_changed=False)
        self.app.print(f"Best band: AUTO on {freqplan.fmt(r['dial_mhz'])} MHz - press Listen + decode "
                       "(Uranus tunes the radio).\n")


# ===================================================================== interference doctor
class DoctorWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        from . import doctor
        self.app, self.doc = app, doctor
        self.title("Uranus - Interference doctor")
        self.geometry("860x640")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        self.results, self.k = {}, 0
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Interference doctor", style="Big.TLabel").pack(anchor="w")
        tk.Label(f, text="One change at a time; Uranus listens for 10 seconds after each and compares it with the "
                         "first measurement.", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 10)).pack(anchor="w")
        self.step = tk.Label(f, text="", bg=G.C["panel"], fg=G.C["ink"], font=(G.UI, 12), wraplength=800,
                             justify="left", anchor="w", padx=12, pady=10)
        self.step.pack(fill="x", pady=10)
        row = ttk.Frame(f)
        row.pack(fill="x")
        self.b_meas = ttk.Button(row, text="Measure (10 s)", command=self.measure)
        self.b_meas.pack(side="left")
        ttk.Button(row, text="Skip step", command=self.next).pack(side="left", padx=6)
        ttk.Button(row, text="Start again", command=self.restart).pack(side="left")
        self.out = tk.Text(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), wrap="word", height=16,
                           highlightthickness=0, padx=8, pady=6)
        self.out.pack(fill="both", expand=True, pady=(10, 0))
        self.show_step()
        self.after(300, self.tick)

    def restart(self):
        self.results, self.k = {}, 0
        self.out.delete("1.0", "end")
        self.show_step()

    def show_step(self):
        if self.k >= len(self.doc.STEPS):
            self.step.config(text="Done. The diagnosis is below.")
            self.b_meas.state(["disabled"])
            self.out.insert("end", "\nDIAGNOSIS\n" + self.doc.verdict(self.results) + "\n")
            return
        key, label, how = self.doc.STEPS[self.k]
        self.b_meas.state(["!disabled"])
        self.step.config(text=f"Step {self.k + 1} of {len(self.doc.STEPS)}: {label}\n{how}")

    def next(self):
        self.k += 1
        self.show_step()

    def measure(self):
        self.b_meas.state(["disabled"])
        self.step.config(text=self.step.cget("text").split("\n")[0] + "\nListening for 10 seconds...")
        dev = G.load_cfg().get("receive", {}).get("audio_device", "default")

        def work():
            from . import monitor
            try:
                self.q.put(self.doc.measure(monitor.record(10, dev)))
            except Exception as e:                  # noqa: BLE001
                self.q.put({"error": str(e)})
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            m = self.q.get_nowait()
            if "error" in m:
                self.out.insert("end", f"No receive audio: {m['error']}\n")
                self.b_meas.state(["!disabled"])
            else:
                key, label, _ = self.doc.STEPS[self.k]
                self.results[key] = m
                line = (f"{label:<24} noise {m['floor_db']:6.1f} dB  hum {m['hum_db']:4.0f} dB  "
                        f"lines {m['comb_lines']:2d}  clicks {m['clicks_per_s']:4.0f}/s")
                if key != "baseline" and "baseline" in self.results:
                    line += "\n   " + self.doc.compare(self.results["baseline"], m, label)
                self.out.insert("end", line + "\n")
                self.next()
        except queue.Empty:
            pass
        self.after(300, self.tick)


# ===================================================================== station health
class HealthWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Station health")
        self.geometry("880x560")
        self.configure(bg=G.C["bg"])
        self.q = queue.Queue()
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        top = ttk.Frame(f)
        top.pack(fill="x")
        ttk.Label(top, text="Station health", style="Big.TLabel").pack(side="left")
        self.score = tk.Label(top, text="", bg=G.C["bg"], fg=G.C["green"], font=(G.UI, 16, "bold"))
        self.score.pack(side="right")
        ttk.Button(f, text="Check again", command=self.run).pack(anchor="w", pady=6)
        self.txt = tk.Text(f, bg=G.C["panel"], fg=G.C["ink"], font=(G.MONO, 10), wrap="word", height=20,
                           highlightthickness=0, padx=8, pady=6)
        for tag, col in (("ok", G.C["green"]), ("warn", G.C["amber"]), ("fail", G.C["red"])):
            self.txt.tag_config(tag, foreground=col, font=(G.MONO, 10, "bold"))
        self.txt.pack(fill="both", expand=True)
        self.run()
        self.after(300, self.tick)

    def run(self):
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "Checking audio, clock, radio, decoders and internet...\n")
        cfg = G.load_cfg()
        busy = bool(self.app.worker) or getattr(self.app, "wefax_on", False)

        def work():
            from . import health
            try:
                self.q.put(health.check(cfg, audio=not busy, cat=not busy))
            except Exception as e:                  # noqa: BLE001
                self.q.put([("Health check", "fail", str(e), "")])
        threading.Thread(target=work, daemon=True).start()

    def tick(self):
        if not self.winfo_exists():
            return
        try:
            res = self.q.get_nowait()
            from . import health
            self.txt.delete("1.0", "end")
            for name, status, detail, fix in res:
                self.txt.insert("end", f"{ {'ok': ' OK ', 'warn': 'WARN', 'fail': 'FAIL'}[status] } ", status)
                self.txt.insert("end", f"{name}: {detail}\n")
                if fix:
                    self.txt.insert("end", f"       Fix: {fix}\n")
            sc = health.score(res)
            self.score.config(text=f"{sc}%", fg=G.C["green"] if sc >= 85 else G.C["amber"] if sc >= 60 else G.C["red"])
        except queue.Empty:
            pass
        self.after(300, self.tick)


# ===================================================================== accessibility
class AccessWindow(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Accessibility, faceplate and layout")
        self.geometry("640x520")
        self.configure(bg=G.C["bg"])
        acc = G.load_cfg().get("access", {})
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Easy for everyone", style="Big.TLabel").pack(anchor="w")
        self.v_speak = tk.BooleanVar(value=bool(acc.get("speak")))
        self.v_large = tk.BooleanVar(value=bool(acc.get("large_text")))
        self.v_cb = tk.BooleanVar(value=bool(acc.get("colourblind")))
        ttk.Checkbutton(f, text="Speak new stations, Pumpkin Reports, charts and alerts", variable=self.v_speak).pack(
            anchor="w", pady=(10, 4))
        ttk.Checkbutton(f, text="Large text (after restart)", variable=self.v_large).pack(anchor="w", pady=4)
        ttk.Checkbutton(f, text="Colour-blind safe colours: blue / orange / yellow (after restart)",
                        variable=self.v_cb).pack(anchor="w", pady=4)
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(12, 4))
        ttk.Label(row, text="Faceplate colours").pack(side="left")
        self.v_theme = tk.StringVar(value=acc.get("theme", "uranus"))
        ttk.Combobox(row, textvariable=self.v_theme, values=list(G.PALETTES), state="readonly", width=14).pack(
            side="left", padx=8)
        row2 = ttk.Frame(f)
        row2.pack(fill="x", pady=(12, 4))
        ttk.Label(row2, text="Screen layout").pack(side="left")
        names = {"auto": "Auto (by screen size)", "full": "Full: every tool a button",
                 "compact": "Compact: fits 768-pixel screens"}
        self.layouts = names
        self.v_layout = tk.StringVar(value=names.get(acc.get("layout", "auto"), names["auto"]))
        ttk.Combobox(row2, textvariable=self.v_layout, values=list(names.values()), state="readonly",
                     width=32).pack(side="left", padx=8)
        tk.Label(f, text="Full is the roomier layout with Station health, Interference doctor, Accessibility, Fax "
                         "gallery and the settings file as buttons; Compact keeps them under More tools. On a small "
                         "screen the button list scrolls.", bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9),
                 wraplength=580, justify="left").pack(anchor="w")
        tk.Label(f, text="uranus = navy (default) · tradewind = brushed grey and amber, like Tradewind · "
                         "highcontrast = black and white. Takes effect when Uranus restarts.",
                 bg=G.C["bg"], fg=G.C["muted"], font=(G.UI, 9), wraplength=580, justify="left").pack(anchor="w")
        b = ttk.Frame(f)
        b.pack(fill="x", pady=(16, 0))
        ttk.Button(b, text="Test speech", command=self.test).pack(side="left")
        ttk.Button(b, text="Save", command=self.save).pack(side="right")

    def test(self):
        from . import speech
        was, speech.ENABLED = speech.ENABLED, True
        speech.say("Uranus. Speech is working.")
        speech.ENABLED = was

    def save(self):
        from . import speech
        err = G.write_keys({("access", "speak"): self.v_speak.get(), ("access", "large_text"): self.v_large.get(),
                            ("access", "colourblind"): self.v_cb.get(), ("access", "theme"): self.v_theme.get(),
                            ("access", "layout"): next(k for k, v in self.layouts.items() if v == self.v_layout.get())})
        if err:
            messagebox.showerror("Accessibility", err, parent=self)
            return
        speech.ENABLED = self.v_speak.get()
        self.app.print("Accessibility saved. Large text, colours, faceplate and screen layout apply when Uranus "
                       "restarts.\n")
        self.destroy()


# ===================================================================== weather fax gallery
class FaxGallery(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Uranus - Weather fax gallery")
        self.geometry("1000x700")
        self.configure(bg=G.C["bg"])
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Newest charts", style="Big.TLabel").pack(side="left")
        ttk.Button(top, text="Open folder", command=lambda: G._open(user_dir("wefax"))).pack(side="right")
        self.cv = tk.Canvas(self, bg=G.C["panel"], highlightthickness=0)
        self.cv.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.photos = []
        self.load()

    def load(self):
        import glob
        files = sorted(glob.glob(os.path.join(user_dir("wefax"), "*.png")), key=os.path.getmtime, reverse=True)[:12]
        if not files:
            self.cv.create_text(20, 20, anchor="nw", text="No charts yet. Weather fax saves each chart here.",
                                fill=G.C["muted"], font=(G.UI, 11))
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            for i, p in enumerate(files):
                self.cv.create_text(20, 20 + 22 * i, anchor="nw", text=os.path.basename(p), fill=G.C["ink"])
            return
        w, h = 310, 200
        for i, p in enumerate(files):
            im = Image.open(p)
            im.thumbnail((w, h))
            ph = ImageTk.PhotoImage(im)
            self.photos.append(ph)
            x, y = 10 + (i % 3) * (w + 16), 10 + (i // 3) * (h + 40)
            item = self.cv.create_image(x, y, anchor="nw", image=ph)
            self.cv.create_text(x, y + h + 4, anchor="nw", text=os.path.basename(p)[:44], fill=G.C["ink"],
                                font=(G.MONO, 9))
            self.cv.tag_bind(item, "<Button-1>", lambda e, path=p: G._open(path))
