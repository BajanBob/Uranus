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
        ttk.Button(ctl, text="Open charts folder", command=lambda: G._open(user_dir("wefax"))).pack(side="left")
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
            self.cb.current(next((k for k, s in enumerate(self.stations) if s[2] == 8503.9), 0))
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
        except queue.Empty:
            pass
        if self.rx and self.rx.state == "image":
            self.status.config(text=f"Receiving a chart · {len(self.rx.lines)} lines "
                                    f"({len(self.rx.lines) / 120:.1f} min)", fg=G.C["decode"])
        self.draw()
        self.after(1000, self.tick)

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
        self.v_band = {}
        for k, b in enumerate(freqplan.BAND_EDGES):
            self.v_band[b] = tk.BooleanVar(value=b == here)
            ttk.Checkbutton(bf, text=freqplan.BAND_NAMES[b], variable=self.v_band[b]).grid(
                row=k // 7, column=k % 7, sticky="w", padx=(0, 10))
        ttk.Label(f, text="Modes", style="CardMuted.TLabel").pack(anchor="w", pady=(8, 0))
        mf = ttk.Frame(f)
        mf.pack(fill="x")
        self.v_mode = {}
        for k, m in enumerate(self.MODES):
            self.v_mode[m] = tk.BooleanVar(value=m in ("ft8", "ft4", "jt65", "q65", "wspr"))
            ttk.Checkbutton(mf, text=m.upper(), variable=self.v_mode[m]).grid(row=k // 6, column=k % 6, sticky="w",
                                                                              padx=(0, 10))
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="Stop on a signal for up to").pack(side="left")
        self.v_dwell = tk.StringVar(value="3")
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
        self.busy, self.top = False, None
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

    def show(self, dial, found, level_db):
        from . import sigint
        self.txt.delete("1.0", "end")
        if dial:
            self.txt.insert("end", f"Dial {dial:.4f} MHz: " + "; ".join(sigint.context(dial)) + "\n", "ctx")
        self.txt.insert("end", f"Audio level {level_db:.0f} dBFS" + (" - very low: raise the radio's USB audio "
                                                                      "or the Windows input level" if level_db < -50
                                                                      else "") + "\n\n", "ctx")
        for f in found:
            at = f" at {f.freq_hz:.0f} Hz" if f.freq_hz else ""
            self.txt.insert("end", f"{f.name}{at}  {f.confidence:.0%}\n", "noise" if f.kind != "signal" else "name")
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
