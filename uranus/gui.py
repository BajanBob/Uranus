"""Uranus control window - the double-click front end (Uranus.exe on Windows).

A dark "faceplate" with a UTC clock, a state lamp, grouped controls, a live
station summary and a live PSK Reporter panel. Buttons run the same code as the
command line, in a background thread, with all output shown in the console.
Every control has hover help. A setup wizard runs on first start.
"""

import contextlib
import io
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import __version__


def base_dir():
    """Folder next to Uranus.exe (frozen) or the repository root."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundled(path):
    root = getattr(sys, "_MEIPASS", base_dir())
    return os.path.join(root, path)


BASE = base_dir()
CONFIG = os.path.join(BASE, "config", "uranus.toml")


def ensure_config():
    if not os.path.exists(CONFIG):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        shutil.copy(bundled(os.path.join("config", "uranus.toml")), CONFIG)


def load_cfg():
    import tomllib
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def write_keys(changes, bands=None):
    """Write {(section, key): value} and {band: active} into uranus.toml, keeping comments.
    Returns an error message, or '' on success."""
    import tomllib
    from . import radios
    with open(CONFIG, encoding="utf-8") as fh:
        t = fh.read()
    for (sec, key), val in changes.items():
        t = radios.set_toml_key(t, sec, key, val)
    for b, on in (bands or {}).items():
        t = radios.set_band_active(t, b, on)
    try:
        tomllib.loads(t)
    except Exception as e:                       # noqa: BLE001
        return f"Not saved - the result would not be valid:\n{e}"
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write(t)
    return ""


# --------------------------------------------------------------------- theme
C = {
    "bg": "#0f1318", "panel": "#171d24", "panel2": "#1f2730", "rule": "#2a333d",
    "ink": "#ece6da", "muted": "#8c98a4", "orange": "#ff9a4a", "green": "#5fd38a",
    "blue": "#6aa8ff", "red": "#ff6b6b", "amber": "#ffcc66", "dark": "#0b0e12",
}
UI = "Segoe UI" if os.name == "nt" else "DejaVu Sans"
MONO = "Consolas" if os.name == "nt" else "DejaVu Sans Mono"

STATES = {                       # lamp colour, label
    "idle": (C["muted"], "STANDBY"),
    "busy": (C["amber"], "WORKING"),
    "dry": (C["amber"], "DRY RUN"),
    "air": (C["red"], "ON AIR"),
    "listen": (C["blue"], "LISTENING"),
    "ok": (C["green"], "READY"),
}


def apply_theme(root):
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=C["bg"])
    st.configure(".", background=C["bg"], foreground=C["ink"], fieldbackground=C["panel2"],
                 bordercolor=C["rule"], lightcolor=C["panel2"], darkcolor=C["panel2"],
                 troughcolor=C["panel"], focuscolor=C["orange"], font=(UI, 10))
    st.configure("TFrame", background=C["bg"])
    st.configure("Card.TFrame", background=C["panel"])
    st.configure("TLabel", background=C["bg"], foreground=C["ink"])
    st.configure("Card.TLabel", background=C["panel"], foreground=C["ink"])
    st.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
    st.configure("CardMuted.TLabel", background=C["panel"], foreground=C["muted"])
    st.configure("Section.TLabel", background=C["bg"], foreground=C["muted"], font=(UI, 8, "bold"))
    st.configure("CardHead.TLabel", background=C["panel"], foreground=C["orange"], font=(UI, 9, "bold"))
    st.configure("Big.TLabel", background=C["bg"], foreground=C["ink"], font=(UI, 16, "bold"))
    st.configure("TButton", background=C["panel2"], foreground=C["ink"], borderwidth=0, padding=(12, 7),
                 relief="flat", anchor="w")
    st.map("TButton", background=[("pressed", C["rule"]), ("active", "#28323d"), ("disabled", C["panel"])],
           foreground=[("disabled", C["muted"])])
    for name, colour, text in (("Accent", C["orange"], C["dark"]), ("Danger", C["red"], C["dark"]),
                               ("Info", C["blue"], C["dark"]), ("Go", C["green"], C["dark"])):
        st.configure(f"{name}.TButton", background=colour, foreground=text, font=(UI, 10, "bold"))
        st.map(f"{name}.TButton", background=[("active", colour), ("pressed", colour)])
    st.configure("TCheckbutton", background=C["bg"], foreground=C["ink"])
    st.map("TCheckbutton", background=[("active", C["bg"])], indicatorcolor=[("selected", C["orange"])])
    st.configure("Card.TCheckbutton", background=C["panel"], foreground=C["ink"], font=(UI, 10, "bold"))
    st.map("Card.TCheckbutton", background=[("active", C["panel"])], indicatorcolor=[("selected", C["green"])])
    st.configure("TCombobox", fieldbackground=C["panel2"], background=C["panel2"], foreground=C["ink"],
                 arrowcolor=C["orange"], padding=4)
    st.map("TCombobox", fieldbackground=[("readonly", C["panel2"])], foreground=[("readonly", C["ink"])],
           selectbackground=[("readonly", C["panel2"])], selectforeground=[("readonly", C["ink"])])
    st.configure("TEntry", fieldbackground=C["panel2"], foreground=C["ink"], insertcolor=C["ink"], padding=4)
    st.configure("TSpinbox", fieldbackground=C["panel2"], foreground=C["ink"], arrowcolor=C["orange"])
    st.configure("Vertical.TScrollbar", background=C["panel2"], arrowcolor=C["muted"])
    root.option_add("*TCombobox*Listbox.background", C["panel2"])
    root.option_add("*TCombobox*Listbox.foreground", C["ink"])
    root.option_add("*TCombobox*Listbox.selectBackground", C["orange"])
    root.option_add("*TCombobox*Listbox.selectForeground", C["dark"])
    root.option_add("*TCombobox*Listbox.font", (UI, 10))


class Tooltip:
    """Hover help: shows `text` (or text()) after a short delay."""

    def __init__(self, widget, text, delay_ms=400):
        self.w, self.text, self.delay, self.tip, self.job = widget, text, delay_ms, None, None
        widget.bind("<Enter>", self._sched, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _sched(self, _e=None):
        self._hide()
        self.job = self.w.after(self.delay, self._show)

    def _show(self):
        txt = self.text() if callable(self.text) else self.text
        if not txt:
            return
        x = self.w.winfo_rootx() + 16
        y = self.w.winfo_rooty() + self.w.winfo_height() + 6
        self.tip = tk.Toplevel(self.w)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        outer = tk.Frame(self.tip, bg=C["orange"], padx=0, pady=0)
        outer.pack()
        tk.Frame(outer, bg=C["orange"], width=3).pack(side="left", fill="y")
        tk.Label(outer, text=txt, justify="left", wraplength=420, bg="#232c36", fg=C["ink"],
                 padx=10, pady=8, font=(UI, 9)).pack(side="left")

    def _hide(self, _e=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


class _QueueWriter(io.TextIOBase):
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(s)
        return len(s)


def draw_logo(parent, bg, size=46):
    cv = tk.Canvas(parent, width=size, height=size, bg=bg, highlightthickness=0)
    s = size / 46
    cv.create_oval(11 * s, 11 * s, 35 * s, 35 * s, fill="#4fb3c2", outline="")
    cv.create_oval(14 * s, 13 * s, 26 * s, 23 * s, fill="#8fd9df", outline="")
    cv.create_oval(4 * s, 19 * s, 42 * s, 27 * s, outline=C["orange"], width=2)
    return cv


# --------------------------------------------------------------------- faceplate
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Uranus {__version__}")
        self.geometry("1120x740")
        self.minsize(940, 620)
        apply_theme(self)
        self.q = queue.Queue()
        self.runner = None
        self.worker = None
        self.reporter = None
        self.state = "idle"
        self._tick = 0
        os.chdir(BASE)
        ensure_config()

        handler = logging.StreamHandler(_QueueWriter(self.q))
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        self._header()
        self._state_strip()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 16))
        self._sidebar(body)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(18, 0))
        cards = ttk.Frame(right)
        cards.pack(fill="x")
        self._station_card(cards)
        self._psk_card(cards)
        self._console(right)

        self.print(f"Uranus {__version__}\nFolder: {BASE}\nSettings: {CONFIG}\n"
                   "Hover over any control for help.\n\n")
        self.refresh_station()
        self.set_state("idle", "Ready. New here? Press 'Setup wizard'.")
        self.after(100, self.poll)
        self.after(600, self._first_run)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------- layout pieces
    def _header(self):
        h = tk.Frame(self, bg=C["bg"])
        h.pack(fill="x", padx=18, pady=(14, 6))
        draw_logo(h, C["bg"]).pack(side="left")
        t = tk.Frame(h, bg=C["bg"])
        t.pack(side="left", padx=(10, 0))
        tk.Label(t, text="URANUS", bg=C["bg"], fg=C["ink"], font=(UI, 22, "bold")).pack(anchor="w")
        tk.Label(t, text=f"Weak-signal beacon · Pumpkin · Cucumber · v{__version__}", bg=C["bg"],
                 fg=C["muted"], font=(UI, 9)).pack(anchor="w")
        clock = tk.Frame(h, bg=C["bg"])
        clock.pack(side="right")
        self.utc = tk.Label(clock, text="--:--:--", bg=C["bg"], fg=C["orange"], font=(MONO, 24, "bold"))
        self.utc.pack(anchor="e")
        self.utc_date = tk.Label(clock, text="", bg=C["bg"], fg=C["muted"], font=(MONO, 9))
        self.utc_date.pack(anchor="e")
        Tooltip(self.utc, "UTC from this PC's clock. FT8, WSPR and Pumpkin need it correct to well under "
                          "1 second: use time.is to check, and Meinberg NTP to keep it right.")
        self.chip = tk.Label(h, text="", bg=C["panel2"], fg=C["ink"], font=(MONO, 12, "bold"), padx=14, pady=6)
        self.chip.pack(side="right", padx=18)
        Tooltip(self.chip, "Your callsign and grid square from the settings. Change them with the Setup wizard.")

    def _state_strip(self):
        s = tk.Frame(self, bg=C["panel"])
        s.pack(fill="x", padx=18, pady=(4, 10))
        self.lamp = tk.Canvas(s, width=22, height=22, bg=C["panel"], highlightthickness=0)
        self.lamp.pack(side="left", padx=(14, 6), pady=10)
        self.lamp_dot = self.lamp.create_oval(3, 3, 19, 19, fill=C["muted"], outline="")
        self.state_lbl = tk.Label(s, text="STANDBY", bg=C["panel"], fg=C["ink"], font=(UI, 12, "bold"), width=11,
                                  anchor="w")
        self.state_lbl.pack(side="left")
        self.status = tk.Label(s, text="", bg=C["panel"], fg=C["muted"], font=(UI, 10), anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        Tooltip(self.lamp, "Grey: standby · Amber: working or dry run · Red: ON AIR · Blue: listening")

    def _sidebar(self, parent):
        side = ttk.Frame(parent, width=250)
        side.pack(side="left", fill="y")
        groups = [
            ("GET STARTED", [
                ("Setup wizard", self.wizard, "Accent", "Step-by-step: callsign and grid, radio (including the "
                 "Icom IC-9100), USB audio codec, CAT port, bands and PSK Reporter."),
                ("Station setup", self.setup, None, "All radio, audio, CAT and band settings on one page."),
                ("Edit settings file", self.edit_config, None, "Open uranus.toml in a text editor for "
                 "everything else (timing, APRS details, frequencies)."),
            ]),
            ("OPERATE", [
                ("Show plan", lambda: self.cli(["plan", "--cycles", "2"]), None,
                 "The next two cycles of transmissions with times and frequencies. Nothing is sent."),
                ("Dry run (1 cycle)", self.dry_run, None,
                 "One full cycle in real time, writing WAV files instead of transmitting."),
                ("ON AIR", self.on_air, "Danger", "Start the transmit schedule on your radio. Asks first."),
                ("Listen + decode", self.listen, "Info", "Decode Pumpkin, UR or Cucumber from the radio every "
                 "slot, log who you hear and, if live upload is on, send the spots to PSK Reporter."),
                ("Chat", self.chat, None, "Keyboard chat over Pumpkin (SSB) or Cucumber (FM), about 11 "
                 "characters per transmission."),
                ("Stop", self.stop, None, "Stop after the current transmission or listening slot."),
            ]),
            ("MAP", [
                ("Station map", lambda: self.cli(["map", "--psk", "--open"]), None,
                 "Map of stations you heard and stations that heard you (from PSK Reporter), by band."),
                ("Map demo", lambda: self.cli(["map", "--demo", "--open"]), None,
                 "The station map with clearly labelled sample stations."),
                ("Open output folder", self.open_out, None, "WAV files, spots log and the map."),
            ]),
            ("TRY IT WITHOUT A RADIO", [
                ("Pumpkin demo  −29 dB", lambda: self.cli(["pumpkin-loopback", "--submode", "PUMPKIN-60",
                                                          "--snr", "-29"]), None,
                 "Encode a PUMPKIN-60 frame, bury it 29 dB under the noise and decode it."),
                ("Cucumber demo  FM", lambda: self.cli(["cucumber-loopback", "--submode", "CUCUMBER-15",
                                                       "--cnr", "-8"]), None,
                 "Send a CUCUMBER-15 frame through a simulated FM link 8 dB below the noise and decode it."),
                ("Link budget", lambda: self.cli(["link-budget", "--example"]), None,
                 "Signal margin for every mode on a reference 400 km beyond-horizon 2 m path."),
            ]),
        ]
        for title, items in groups:
            ttk.Label(side, text=title, style="Section.TLabel").pack(anchor="w", pady=(10, 4))
            for text, cmd, style, tip in items:
                b = ttk.Button(side, text=text, command=cmd, style=f"{style}.TButton" if style else "TButton")
                b.pack(fill="x", pady=2)
                Tooltip(b, tip)

    def _card(self, parent, title):
        f = ttk.Frame(parent, style="Card.TFrame", padding=(16, 12))
        f.pack(side="left", fill="both", expand=True, padx=(0, 12) if title.startswith("STATION") else 0)
        ttk.Label(f, text=title, style="CardHead.TLabel").pack(anchor="w", pady=(0, 6))
        return f

    def _station_card(self, parent):
        f = self._card(parent, "STATION")
        self.st_rows = {}
        for key, tip in [("Radio", "Radio or SDR profile. Change it in the Setup wizard or Station setup."),
                         ("Transmit with", "dry-run writes WAV files only; hamlib drives a CAT rig through "
                                           "rigctld; hackrf drives a HackRF One."),
                         ("Audio to radio", "Sound output that feeds the radio. ★ marks a radio USB codec, "
                                            "such as the IC-9100's 'USB Audio CODEC'."),
                         ("Audio from radio", "Sound input carrying the receiver's audio for decoding."),
                         ("Bands", "Bands the beacon cycles through.")]:
            row = ttk.Frame(f, style="Card.TFrame")
            row.pack(fill="x", pady=1)
            k = ttk.Label(row, text=key, style="CardMuted.TLabel", width=15)
            k.pack(side="left")
            v = ttk.Label(row, text="", style="Card.TLabel")
            v.pack(side="left", fill="x")
            Tooltip(k, tip)
            Tooltip(v, tip)
            self.st_rows[key] = v

    def _psk_card(self, parent):
        f = self._card(parent, "PSK REPORTER · LIVE UPLOAD")
        top = ttk.Frame(f, style="Card.TFrame")
        top.pack(fill="x")
        self.v_psk = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(top, text="Upload my decodes", variable=self.v_psk, style="Card.TCheckbutton",
                             command=self.psk_toggle)
        cb.pack(side="left")
        Tooltip(cb, "When on, every station you decode while listening is reported to PSK Reporter, so it "
                    "appears on pskreporter.info alongside FT8 and WSPR spots. Turning it on or off takes "
                    "effect immediately, even while listening.")
        self.v_server = tk.StringVar(value="Test server")
        sv = ttk.Combobox(top, textvariable=self.v_server, values=["Live", "Test server"], state="readonly",
                          width=11)
        sv.pack(side="right")
        sv.bind("<<ComboboxSelected>>", lambda e: self.psk_server())
        Tooltip(sv, "Test server: PSK Reporter's test port, for checking your setup (spots are not shown on "
                    "the public map).\nLive: report.pskreporter.info, the public map. Use Live once a test "
                    "upload has worked.")
        self.psk_lamp = tk.Label(f, text="", bg=C["panel"], fg=C["muted"], font=(UI, 10, "bold"),
                                 anchor="w")
        self.psk_lamp.pack(fill="x", pady=(8, 2))
        self.psk_stats = tk.Label(f, text="", bg=C["panel"], fg=C["ink"], font=(MONO, 10), anchor="w",
                                  justify="left")
        self.psk_stats.pack(fill="x")
        Tooltip(self.psk_stats, "Decoded: stations heard this session. Uploaded: sent to PSK Reporter. "
                                "Waiting: queued for the next upload. PSK Reporter asks programs to upload "
                                "at most every 5 minutes, so spots are sent in batches.")
        b = ttk.Button(f, text="Open my PSK Reporter map", command=self.psk_open)
        b.pack(anchor="w", pady=(8, 0))
        Tooltip(b, "Open pskreporter.info in your browser, showing who has heard your callsign.")

    def _console(self, parent):
        ttk.Label(parent, text="CONSOLE", style="Section.TLabel").pack(anchor="w", pady=(14, 4))
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, bg=C["dark"], fg="#b8f28a", insertbackground=C["ink"], font=(MONO, 10),
                            wrap="word", relief="flat", padx=10, pady=8, highlightthickness=1,
                            highlightbackground=C["rule"])
        sb = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)

    # ---------------------------------------------------------- helpers
    def print(self, s):
        self.text.insert("end", s)
        self.text.see("end")

    def set_state(self, state, msg=None):
        self.state = state
        colour, label = STATES.get(state, STATES["idle"])
        self.lamp.itemconfig(self.lamp_dot, fill=colour)
        self.state_lbl.config(text=label, fg=colour if state != "idle" else C["ink"])
        if msg is not None:
            self.status.config(text=msg)

    def set_status(self, msg, colour=None):
        """Older callers: message only (colour hints map to a state)."""
        state = {"#cdeccd": "ok", "#ffb3b3": "air", "#cfe3ff": "listen", "#fff3c4": "busy"}.get(colour)
        if state:
            self.set_state(state, msg)
        else:
            self.status.config(text=msg)

    def poll(self):
        try:
            while True:
                self.print(self.q.get_nowait())
        except queue.Empty:
            pass
        if self.worker and not self.worker.is_alive():
            self.worker = None
            self.runner = None
            if self.reporter:
                self.reporter.stop.set()
                threading.Thread(target=self.reporter.flush, daemon=True).start()
            self.set_state("idle", "Finished.")
        self._tick += 1
        if self._tick % 5 == 0:
            now = time.gmtime()
            self.utc.config(text=time.strftime("%H:%M:%S", now))
            self.utc_date.config(text=time.strftime("UTC · %a %d %b %Y", now))
            self.update_psk()
        self.after(100, self.poll)

    def busy(self):
        if self.worker:
            messagebox.showinfo("Busy", "Something is already running. Press Stop first.")
            return True
        return False

    def start(self, fn, status, state="busy"):
        if self.busy():
            return
        self.set_state(state, status)

        def wrap():
            w = _QueueWriter(self.q)
            with contextlib.redirect_stdout(w), contextlib.redirect_stderr(w):
                try:
                    fn()
                except SystemExit as e:
                    if e.code not in (None, 0):
                        print(f"\n{e.code}\n")
                except Exception as e:      # noqa: BLE001
                    print(f"\nERROR: {e}\n")
        self.worker = threading.Thread(target=wrap, daemon=True)
        self.worker.start()

    def refresh_station(self):
        from . import audiodev
        try:
            cfg = load_cfg()
        except Exception as e:              # noqa: BLE001
            self.print(f"Could not read settings: {e}\n")
            return
        st, rc, rx = cfg.get("station", {}), cfg.get("radio", {}), cfg.get("receive", {})
        self.chip.config(text=f"{st.get('callsign', '?')} · {st.get('grid', '?')}")
        prof = rc.get("profile") or "not chosen"
        self.st_rows["Radio"].config(text=prof)
        self.st_rows["Transmit with"].config(text=rc.get("backend", "dry-run"))
        for key, spec, kind in (("Audio to radio", rc.get("audio_device", "default"), "out"),
                                ("Audio from radio", rx.get("audio_device", "default"), "in")):
            mark = "★ " if audiodev.is_codec(str(spec)) else ""
            self.st_rows[key].config(text=f"{mark}{spec}")
        names = {"2m": "2 m", "1.25m": "1.25 m", "70cm": "70 cm"}
        on = [names.get(b["name"], b["name"]) for b in cfg.get("band", []) if b.get("active", True)]
        self.st_rows["Bands"].config(text=" · ".join(on) or "none")
        rep = cfg.get("reporting", {})
        self.v_psk.set(bool(rep.get("pskreporter", False)))
        self.v_server.set("Test server" if rep.get("pskreporter_test_server", True) else "Live")
        self.cfg_call = st.get("callsign", "")
        self.update_psk()

    # ---------------------------------------------------------- PSK Reporter live panel
    def _make_reporter(self):
        from . import pskreporter
        cfg = load_cfg()
        return pskreporter.Reporter(cfg["station"]["callsign"], cfg["station"]["grid"],
                                    test=self.v_server.get() != "Live")

    def psk_toggle(self):
        on = self.v_psk.get()
        err = write_keys({("reporting", "pskreporter"): on})
        if err:
            messagebox.showerror("PSK Reporter", err)
            return
        listening = self.runner is not None and hasattr(self.runner, "reporter")
        if on and listening and self.runner.reporter is None:
            self.reporter = self._make_reporter()
            self.runner.reporter = self.reporter
            self.print("PSK Reporter: live upload switched ON for this listening session.\n")
        elif not on and self.reporter:
            if listening:
                self.runner.reporter = None
            rep, self.reporter = self.reporter, None
            rep.stop.set()
            threading.Thread(target=rep.flush, daemon=True).start()
            self.print("PSK Reporter: upload switched OFF (spots already waiting were sent).\n")
        self.update_psk()

    def psk_server(self):
        live = self.v_server.get() == "Live"
        if live and not messagebox.askyesno("PSK Reporter", "Send spots to the LIVE PSK Reporter map?\n\n"
                                            "Do this once a test upload has worked."):
            self.v_server.set("Test server")
            return
        write_keys({("reporting", "pskreporter_test_server"): not live})
        if self.reporter:
            self.print("PSK Reporter: server change takes effect the next time you press Listen.\n")

    def psk_open(self):
        call = getattr(self, "cfg_call", "") or ""
        webbrowser.open("https://pskreporter.info/pskmap.html?preset&callsign=" + call + "&timerange=86400")

    def update_psk(self):
        if not hasattr(self, "psk_stats"):
            return
        if not self.v_psk.get():
            self.psk_lamp.config(text="●  Off", fg=C["muted"])
            self.psk_stats.config(text="Tick 'Upload my decodes', then press\nListen + decode.")
            return
        if not self.reporter:
            self.psk_lamp.config(text="●  Armed — starts when you press Listen", fg=C["amber"])
            self.psk_stats.config(text=f"Server: {self.v_server.get()}\nDecoded 0 · Uploaded 0 · Waiting 0")
            return
        s = self.reporter.status()
        if s["last_error"]:
            self.psk_lamp.config(text="●  Upload problem — will retry", fg=C["red"])
        else:
            self.psk_lamp.config(text=f"●  Live · {s['server']} server", fg=C["green"])
        last = time.strftime("%H:%M:%S UTC", time.gmtime(s["last_sent"])) if s["last_sent"] else "not yet"
        m, sec = divmod(s["next_in_s"], 60)
        txt = (f"Decoded {s['added']} · Uploaded {s['sent']} · Waiting {s['queued']}\n"
               f"Last upload {last} · next in {m}:{sec:02d}")
        if s["last_error"]:
            txt += f"\n{s['last_error'][:60]}"
        self.psk_stats.config(text=txt)

    # ---------------------------------------------------------- actions
    def cli(self, argv):
        from . import cli
        self.print(f"\n> uranus {' '.join(argv)}\n")
        self.start(lambda: cli.main(["-c", CONFIG] + argv), "Working...")

    def _runner(self, dry):
        from . import scheduler
        from .radio import DryRunRadio, HamlibRadio
        cfg, slots = scheduler.load_config(CONFIG)
        rc = cfg["radio"]
        if dry or rc.get("backend", "dry-run") == "dry-run":
            radio = DryRunRadio(os.path.join(BASE, "out"))
        elif rc.get("backend") == "hackrf":
            from .sdr import HackRFRadio
            sd = cfg.get("sdr", {})
            radio = HackRFRadio(sd.get("hackrf_txvga", 10), sd.get("hackrf_amp", False),
                                sd.get("sample_rate", 2_400_000), sd.get("offset_hz", 200_000),
                                rc.get("max_tx_s", 320))
        else:
            radio = HamlibRadio(rc["rigctld_host"], rc["rigctld_port"],
                                rc.get("audio_device", "default"), max_tx_s=rc.get("max_tx_s", 320))
        return scheduler.Runner(cfg, slots, radio)

    def dry_run(self):
        def go():
            self.runner = self._runner(True)
            self.runner.run(cycles=1)
        self.print("\n> dry run: one full cycle in real time, WAV files go to the 'out' folder\n")
        self.start(go, "Dry run in progress — nothing is transmitted. Press Stop to end.", "dry")

    def on_air(self):
        if not messagebox.askyesno(
                "Transmit?", "Start transmitting with your settings?\n\n"
                "Check: rigctld running, 'Transmit with' = hamlib, the radio's USB audio codec chosen, "
                "PC clock accurate, and every enabled frequency permitted by your licence."):
            return

        def go():
            self.runner = self._runner(False)
            self.runner.run()
        self.print("\n> ON AIR\n")
        self.start(go, "Transmitting on schedule. Press Stop to end.", "air")

    def listen(self):
        if self.busy():
            return
        if self.v_psk.get():
            self.reporter = self._make_reporter()

        def go():
            from . import monitor
            cfg = load_cfg()
            self.runner = monitor.Listener(cfg, self.reporter)
            self.runner.run()
        up = " and uploading to PSK Reporter" if self.reporter else ""
        self.print(f"\n> listen: decoding from the radio{up}; spots go to out/spots.jsonl\n")
        self.start(go, f"Decoding every slot{up}. Press Stop to end.", "listen")

    def stop(self):
        if self.runner:
            self.runner.stop.set()
            self.set_state("busy", "Stopping after the current transmission or slot...")
        elif self.worker:
            self.set_state("busy", "Waiting for the current task to finish...")

    def setup(self):
        SetupWindow(self)

    def wizard(self):
        SetupWizard(self)

    def _first_run(self):
        try:
            call = load_cfg().get("station", {}).get("callsign", "")
        except Exception:                    # noqa: BLE001
            return
        if call in ("", "N0CALL"):
            self.print("First start: opening the Setup wizard.\n")
            self.wizard()

    def chat(self):
        if self.worker and not isinstance(self.runner, type(None)):
            messagebox.showinfo("Busy", "Stop the beacon or listener first: chat needs the radio.")
            return
        ChatWindow(self)

    def edit_config(self):
        self.print(f"\nOpening {CONFIG}\n")
        _open(CONFIG)

    def open_out(self):
        out = os.path.join(BASE, "out")
        os.makedirs(out, exist_ok=True)
        _open(out)

    def on_close(self):
        if self.runner:
            self.runner.stop.set()
        if self.reporter:
            self.reporter.stop.set()
            self.reporter.flush()
        self.destroy()


# --------------------------------------------------------------------- shared pickers
def serial_ports():
    try:
        import serial.tools.list_ports
        return [f"{p.device}  —  {p.description}" if p.description and p.description != "n/a" else p.device
                for p in serial.tools.list_ports.comports()]
    except Exception:                        # noqa: BLE001
        return []


def port_from_label(label):
    return (label or "").split("  —  ")[0].strip()


def port_label(port, ports):
    return next((p for p in ports if port_from_label(p) == port), port)


def ic9100_note(profile_name):
    if "9100" in profile_name:
        return ("IC-9100: plug in the USB cable, install Icom's USB driver, then set on the radio: "
                "CI-V USB Baud Rate = 19200, CI-V Address = 7C, CI-V USB Echo Back = OFF, "
                "USB AF output level ~50%, DATA MOD = USB. Use USB-D for FT8/WSPR/Pumpkin and FM-D for "
                "APRS/Cucumber.")
    return ""


class SetupWindow(tk.Toplevel):
    """Station setup: radio/SDR, backend, CAT, audio, bands - all from lists, with hover help."""

    def __init__(self, app):
        super().__init__(app)
        from . import audiodev, radios
        import tomllib
        self.app, self.radios, self.ad = app, radios, audiodev
        self.title("Uranus - Station setup")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        try:
            with open(CONFIG, "rb") as f:
                self.cfg = tomllib.load(f)
        except Exception as e:              # noqa: BLE001
            messagebox.showerror("Settings", f"Could not read {CONFIG}:\n{e}")
            self.destroy()
            return
        rc, rx, sd = self.cfg.get("radio", {}), self.cfg.get("receive", {}), self.cfg.get("sdr", {})
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both")
        ttk.Label(f, text="Station setup", style="Big.TLabel").grid(row=0, column=0, columnspan=3, sticky="w",
                                                                    pady=(0, 10))
        self.v = {}
        row = [1]

        def add(label, widget, tip):
            lab = ttk.Label(f, text=label, style="Muted.TLabel")
            lab.grid(row=row[0], column=0, sticky="e", padx=8, pady=4)
            widget.grid(row=row[0], column=1, sticky="we", padx=8, pady=4)
            Tooltip(lab, tip)
            Tooltip(widget, tip)
            row[0] += 1

        names = [p.name for p in radios.PROFILES]
        self.v["profile"] = tk.StringVar(value=rc.get("profile") if rc.get("profile") in names else names[0])
        cb = ttk.Combobox(f, textvariable=self.v["profile"], values=names, state="readonly", width=50)
        add("Radio / SDR", cb, lambda: radios.BY_NAME[self.v["profile"].get()].help())
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_profile())
        self.info = tk.Label(f, text="", justify="left", wraplength=520, anchor="w", fg=C["muted"], bg=C["bg"],
                             font=(UI, 9))
        self.info.grid(row=row[0], column=0, columnspan=3, sticky="we", padx=8, pady=(0, 8))
        row[0] += 1

        self.v["backend"] = tk.StringVar(value=rc.get("backend", "dry-run"))
        add("Transmit with", ttk.Combobox(f, textvariable=self.v["backend"], values=["dry-run", "hamlib", "hackrf"],
                                          state="readonly", width=20),
            "dry-run: write WAV files only, nothing is sent.\nhamlib: a CAT-controlled rig (start rigctld below).\n"
            "hackrf: a HackRF One SDR (experimental; band-pass filter required).")

        mf = ttk.Frame(f)
        self.v["hamlib_model"] = tk.StringVar(value=str(rc.get("hamlib_model", "")))
        ttk.Entry(mf, textvariable=self.v["hamlib_model"], width=8).pack(side="left")
        bfind = ttk.Button(mf, text="Find", command=self.find_model)
        bfind.pack(side="left", padx=4)
        Tooltip(bfind, "Look the selected radio up in Hamlib's list (rigctl -l) and fill in its model number.")
        add("Hamlib model no.", mf, "Hamlib's number for your rig. Press Find, or run 'rigctl -l' and copy it.")

        self.ports = serial_ports()
        self.v["cat_port"] = tk.StringVar(value=port_label(rc.get("cat_port", ""), self.ports)
                                          or (self.ports[0] if self.ports else ""))
        self.port_cb = ttk.Combobox(f, textvariable=self.v["cat_port"], values=self.ports, width=50)
        add("CAT port", self.port_cb,
            "The rig's CAT (control) port, e.g. COM5 on Windows, /dev/ttyUSB0 on Linux/Pi. The IC-9100 shows "
            "as 'Silicon Labs CP210x USB to UART Bridge'.")
        self.v["cat_baud"] = tk.StringVar(value=str(rc.get("cat_baud", 19200)))
        add("CAT speed", ttk.Combobox(f, textvariable=self.v["cat_baud"],
                                      values=["4800", "9600", "19200", "38400", "57600", "115200"], width=20),
            "Must match the CI-V / CAT baud rate set in the radio's menu (IC-9100: CI-V USB Baud Rate).")

        self.v["audio_out"] = tk.StringVar(value=audiodev.label_for(rc.get("audio_device", "default"), "out"))
        self.out_cb = ttk.Combobox(f, textvariable=self.v["audio_out"], values=audiodev.choices("out"), width=50)
        add("Audio to radio (TX)", self.out_cb,
            "Sound output that feeds the radio. ★ marks a radio's built-in USB codec.\n" + audiodev.CODEC_HELP)
        self.v["audio_in"] = tk.StringVar(value=audiodev.label_for(rx.get("audio_device", "default"), "in"))
        self.in_cb = ttk.Combobox(f, textvariable=self.v["audio_in"], values=audiodev.choices("in"), width=50)
        add("Audio from radio (RX)", self.in_cb,
            "Sound input carrying the receiver's audio, for listen mode. Usually the same USB Audio CODEC.")
        self.v["source"] = tk.StringVar(value=rx.get("source", "audio"))
        add("Listen with", ttk.Combobox(f, textvariable=self.v["source"], values=["audio", "rtl_fm"], state="readonly",
                                        width=20),
            "audio: the rig (or SDR software) through a sound input.\nrtl_fm: an RTL-SDR dongle directly.")

        bf = ttk.Frame(f)
        active = {b["name"]: b.get("active", True) for b in self.cfg.get("band", [])}
        band_tips = {"2m": "144-148 MHz. APRS 144.390, FT8 144.174, WSPR 144.490, Pumpkin.",
                     "1.25m": "222-225 MHz (220 MHz band). ITU Region 2 only; check your licence. "
                              "Needs a transverter, a tri-band FM rig or an SDR. Not on the IC-9100.",
                     "70cm": "420-450 MHz. FT8 432.174, WSPR 432.300, Pumpkin."}
        for b in ("2m", "1.25m", "70cm"):
            self.v["band_" + b] = tk.BooleanVar(value=bool(active.get(b, False)))
            c = ttk.Checkbutton(bf, text={"2m": "2 m", "1.25m": "1.25 m (220)", "70cm": "70 cm"}[b],
                                variable=self.v["band_" + b])
            c.pack(side="left", padx=(0, 12))
            Tooltip(c, band_tips[b])
        add("Bands", bf, "Bands the beacon cycles through. Frequencies you disabled for licensing reasons stay "
                         "disabled.")

        lo = next((b.get("transverter_lo_mhz", 0.0) for b in self.cfg.get("band", []) if b["name"] == "1.25m"), 0.0)
        self.v["lo"] = tk.StringVar(value=str(lo))
        add("1.25 m transverter LO (MHz)", ttk.Entry(f, textvariable=self.v["lo"], width=10),
            "0 if the radio tunes 222 MHz itself. With a transverter: 194 for a 28 MHz IF, 78 for a 144 MHz IF.")
        self.v["txvga"] = tk.StringVar(value=str(sd.get("hackrf_txvga", 10)))
        add("HackRF TX gain (dB)", ttk.Spinbox(f, from_=0, to=47, textvariable=self.v["txvga"], width=8),
            "0-47 dB. Start low and measure your output after the band-pass filter.")

        bb = ttk.Frame(f)
        bb.grid(row=row[0], column=0, columnspan=3, sticky="e", pady=(14, 0))
        for text, cmd, style, tip in [
                ("Refresh devices", self.refresh, None, "Look again for COM ports and sound devices, e.g. after "
                                                        "switching the radio on or plugging in its USB cable."),
                ("Start rigctld", self.start_rigctld, None, "Start Hamlib's rig server with the model, port and "
                                                            "speed above."),
                ("Save", self.save, "Accent", "Write these choices into uranus.toml (other settings are kept)."),
                ("Close", self.destroy, None, "Close without saving.")]:
            b = ttk.Button(bb, text=text, command=cmd, style=f"{style}.TButton" if style else "TButton")
            b.pack(side="left", padx=4)
            Tooltip(b, tip)
        self.on_profile(initial=True)

    def refresh(self):
        self.ports = serial_ports()
        self.port_cb.config(values=self.ports)
        self.out_cb.config(values=self.ad.choices("out"))
        self.in_cb.config(values=self.ad.choices("in"))
        self.app.print(f"Found {len(self.ports)} COM port(s); codec "
                       f"{'found' if self.ad.best_codec('out') else 'not detected'}.\n")

    def on_profile(self, initial=False):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        self.info.config(text=(p.help().split("\n", 1)[1] + ("\n\n" + ic9100_note(p.name) if ic9100_note(p.name)
                                                              else "")))
        if not initial:
            self.v["backend"].set({"hamlib": "hamlib", "hackrf": "hackrf"}.get(p.backend, self.v["backend"].get()))
            if p.backend == "rtl_fm":
                self.v["source"].set("rtl_fm")
            if p.usb_audio == "built-in" and p.backend == "hamlib":
                self.v["audio_out"].set(self.ad.choices("out")[0])
                self.v["audio_in"].set(self.ad.choices("in")[0])
                self.v["source"].set("audio")
            if "9100" in p.name:
                self.v["cat_baud"].set("19200")
            for b in ("2m", "1.25m", "70cm"):
                if b not in p.bands:
                    self.v["band_" + b].set(False)
            if p.hamlib_name:
                self.find_model(quiet=True)

    def find_model(self, quiet=False):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        if not p.hamlib_name:
            if not quiet:
                messagebox.showinfo("Hamlib", "This profile is not CAT-controlled through Hamlib.")
            return
        num, msg = self.radios.find_hamlib_model(p.hamlib_name)
        if num:
            self.v["hamlib_model"].set(str(num))
            self.app.print(f"Hamlib: {msg}\n")
        elif not quiet:
            messagebox.showinfo("Hamlib", msg)

    def save(self):
        try:
            lo = float(self.v["lo"].get() or 0)
        except ValueError:
            messagebox.showerror("Settings", "Transverter LO must be a number in MHz.")
            return
        ch = {("radio", "profile"): self.v["profile"].get(),
              ("radio", "backend"): self.v["backend"].get(),
              ("radio", "cat_port"): port_from_label(self.v["cat_port"].get()),
              ("radio", "cat_baud"): int(self.v["cat_baud"].get() or 19200),
              ("radio", "audio_device"): self.ad.spec_from_label(self.v["audio_out"].get()),
              ("receive", "audio_device"): self.ad.spec_from_label(self.v["audio_in"].get()),
              ("receive", "source"): self.v["source"].get(),
              ("sdr", "hackrf_txvga"): int(float(self.v["txvga"].get() or 10))}
        if self.v["hamlib_model"].get().strip().isdigit():
            ch[("radio", "hamlib_model")] = int(self.v["hamlib_model"].get())
        err = write_keys(ch, {b: self.v["band_" + b].get() for b in ("2m", "1.25m", "70cm")})
        if err:
            messagebox.showerror("Settings", err)
            return
        with open(CONFIG, encoding="utf-8") as fh:
            t = self._set_band_key(fh.read(), "1.25m", "transverter_lo_mhz", lo)
        with open(CONFIG, "w", encoding="utf-8") as fh:
            fh.write(t)
        self.app.print(f"\nSaved station setup to {CONFIG}\n")
        self.app.refresh_station()
        self.app.set_state("ok", "Station setup saved.")

    @staticmethod
    def _set_band_key(t, band, key, value):
        out, inb = [], False
        for ln in t.splitlines(keepends=True):
            s = ln.strip()
            if s == "[[band]]":
                inb = False
            if s.startswith("name =") and s.split("=", 1)[1].split("#")[0].strip().strip('"') == band:
                inb = True
            elif inb and s.startswith(key + " ="):
                comment = ("  " + ln[ln.index("#"):].rstrip("\n")) if "#" in ln else ""
                ln = f"{key} = {value}{comment}\n"
                inb = False
            out.append(ln)
        return "".join(out)

    def start_rigctld(self):
        start_rigctld(self.app, self.v["hamlib_model"].get(), port_from_label(self.v["cat_port"].get()),
                      self.v["cat_baud"].get(), self.cfg.get("radio", {}).get("rigctld_port", 4532))


def start_rigctld(app, model, port, baud, tcp_port=4532):
    exe = shutil.which("rigctld")
    if not exe:
        messagebox.showerror("rigctld", "rigctld not found. Install Hamlib for Windows and add its bin "
                                        "folder to your PATH.")
        return False
    model, port = str(model).strip(), str(port).strip()
    if not (model.isdigit() and port):
        messagebox.showerror("rigctld", "Set the Hamlib model number and CAT port first.")
        return False
    subprocess.Popen([exe, "-m", model, "-r", port, "-s", str(baud), "-t", str(tcp_port)])
    app.print(f"Started rigctld -m {model} -r {port} -s {baud} -t {tcp_port}\n")
    return True


# --------------------------------------------------------------------- setup wizard
WSPR_DBM = [(0, "1 mW"), (10, "10 mW"), (20, "100 mW"), (23, "200 mW"), (27, "500 mW"), (30, "1 W"),
            (33, "2 W"), (37, "5 W"), (40, "10 W"), (43, "20 W"), (47, "50 W"), (50, "100 W")]


class SetupWizard(tk.Toplevel):
    """Six short steps from a fresh install to a working station, with hover help throughout."""

    STEPS = ["Station", "Radio", "Connection", "Bands", "PSK Reporter", "Finish"]

    def __init__(self, app):
        super().__init__(app)
        from . import audiodev, radios
        self.app, self.radios, self.ad = app, radios, audiodev
        self.title("Uranus - Setup wizard")
        self.configure(bg=C["bg"])
        self.geometry("760x600")
        self.resizable(False, False)
        try:
            self.cfg = load_cfg()
        except Exception as e:               # noqa: BLE001
            messagebox.showerror("Settings", f"Could not read {CONFIG}:\n{e}")
            self.destroy()
            return
        st, rc, rx = self.cfg.get("station", {}), self.cfg.get("radio", {}), self.cfg.get("receive", {})
        rep = self.cfg.get("reporting", {})
        names = [p.name for p in radios.PROFILES]
        active = {b["name"]: b.get("active", True) for b in self.cfg.get("band", [])}
        dbm = int(st.get("wspr_power_dbm", 37))
        self.v = {
            "call": tk.StringVar(value="" if st.get("callsign") == "N0CALL" else st.get("callsign", "")),
            "grid": tk.StringVar(value=st.get("grid6") or st.get("grid", "")),
            "power": tk.StringVar(value=next((f"{d} dBm  ({w})" for d, w in WSPR_DBM if d == dbm), f"{dbm} dBm")),
            "profile": tk.StringVar(value=rc.get("profile") if rc.get("profile") in names else "Icom IC-9100"),
            "backend": tk.StringVar(value=rc.get("backend", "dry-run")),
            "model": tk.StringVar(value=str(rc.get("hamlib_model", ""))),
            "port": tk.StringVar(value=rc.get("cat_port", "")),
            "baud": tk.StringVar(value=str(rc.get("cat_baud", 19200))),
            "out": tk.StringVar(value=audiodev.label_for(rc.get("audio_device", "default"), "out")),
            "in": tk.StringVar(value=audiodev.label_for(rx.get("audio_device", "default"), "in")),
            "psk": tk.BooleanVar(value=bool(rep.get("pskreporter", True))),
            "psk_live": tk.BooleanVar(value=not rep.get("pskreporter_test_server", True)),
            "contact": tk.StringVar(value=rep.get("pskreporter_contact", "")),
        }
        for b in ("2m", "1.25m", "70cm"):
            self.v["band_" + b] = tk.BooleanVar(value=bool(active.get(b, b != "1.25m")))

        self.steps_bar = tk.Frame(self, bg=C["bg"])
        self.steps_bar.pack(fill="x", padx=24, pady=(18, 6))
        self.step_lbls = []
        for i, name in enumerate(self.STEPS):
            lb = tk.Label(self.steps_bar, text=f"{i + 1}  {name}", bg=C["bg"], fg=C["muted"], font=(UI, 9, "bold"),
                          padx=8, pady=4)
            lb.pack(side="left")
            self.step_lbls.append(lb)
        self.body = ttk.Frame(self, padding=(24, 10))
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(self, padding=(24, 0, 24, 18))
        nav.pack(fill="x")
        self.b_back = ttk.Button(nav, text="◀  Back", command=lambda: self.goto(self.i - 1))
        self.b_back.pack(side="left")
        self.b_next = ttk.Button(nav, text="Next  ▶", style="Accent.TButton", command=self.next)
        self.b_next.pack(side="right")
        ttk.Button(nav, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.pages = [self.p_station, self.p_radio, self.p_connection, self.p_bands, self.p_psk, self.p_finish]
        self.i = 0
        self.goto(0)

    # ---------------------------------------------------------- page helpers
    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _title(self, title, sub):
        ttk.Label(self.body, text=title, style="Big.TLabel").pack(anchor="w")
        tk.Label(self.body, text=sub, bg=C["bg"], fg=C["muted"], font=(UI, 10), wraplength=700, justify="left",
                 anchor="w").pack(fill="x", pady=(4, 14))

    def _field(self, parent, label, widget_fn, tip):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=5)
        lab = ttk.Label(row, text=label, style="Muted.TLabel", width=22)
        lab.pack(side="left")
        w = widget_fn(row)
        w.pack(side="left", fill="x", expand=True)
        Tooltip(lab, tip)
        Tooltip(w, tip)
        return w

    def _note(self, text, colour=None):
        n = tk.Label(self.body, text=text, bg=C["panel"], fg=colour or C["ink"], font=(UI, 9), wraplength=680,
                     justify="left", anchor="w", padx=12, pady=10)
        n.pack(fill="x", pady=(12, 0))
        return n

    def goto(self, i):
        i = max(0, min(len(self.pages) - 1, i))
        self.i = i
        for k, lb in enumerate(self.step_lbls):
            lb.config(fg=C["dark"] if k == i else (C["green"] if k < i else C["muted"]),
                      bg=C["orange"] if k == i else C["bg"])
        self._clear()
        self.pages[i]()
        self.b_back.state(["disabled"] if i == 0 else ["!disabled"])
        self.b_next.config(text="Save and finish" if i == len(self.pages) - 1 else "Next  ▶")

    def next(self):
        ok = self.validate(self.i)
        if ok is not True:
            messagebox.showwarning("Please check", ok, parent=self)
            return
        if self.i == len(self.pages) - 1:
            self.finish()
        else:
            self.goto(self.i + 1)

    def validate(self, i):
        if i == 0:
            call = self.v["call"].get().strip().upper()
            if not re.fullmatch(r"[A-Z0-9]{3,6}", call) or not re.search(r"\d", call):
                return "Callsign: 3 to 6 letters and digits, with at least one digit, and no '/' (e.g. 8P5AB)."
            if not re.fullmatch(r"[A-Ra-r]{2}\d{2}([A-Xa-x]{2})?", self.v["grid"].get().strip()):
                return "Grid square: 4 or 6 characters, e.g. GK03 or GK03ec."
        if i == 2 and self.v["backend"].get() == "hamlib":
            if not self.v["model"].get().strip().isdigit():
                return "Enter the Hamlib model number (press Find), or choose 'dry-run' for now."
            if not port_from_label(self.v["port"].get()):
                return "Choose the radio's COM port, or choose 'dry-run' for now."
        return True

    # ---------------------------------------------------------- pages
    def p_station(self):
        self._title("Your station", "This goes into every beacon you send. You can change it later.")
        self._field(self.body, "Callsign", lambda p: ttk.Entry(p, textvariable=self.v["call"], width=14),
                    "Your callsign, 3-6 characters, no '/'. WSPR and Pumpkin carry it on air.")
        self._field(self.body, "Grid square", lambda p: ttk.Entry(p, textvariable=self.v["grid"], width=10),
                    "Your Maidenhead locator. 4 characters are sent on air (GK03); 6 characters (GK03ec) give "
                    "more accurate map distances. Barbados is GK03.")
        self._field(self.body, "Transmit power",
                    lambda p: ttk.Combobox(p, textvariable=self.v["power"], state="readonly", width=20,
                                           values=[f"{d} dBm  ({w})" for d, w in WSPR_DBM]),
                    "The power you really send, reported in WSPR. Only these dBm values are valid in WSPR.")
        self._note("Your latitude and longitude for APRS are worked out from the grid square.", C["muted"])

    def p_radio(self):
        self._title("Your radio", "Pick it from the list. Hover over the list for what each radio can do.")
        names = [p.name for p in self.radios.PROFILES]
        cb = self._field(self.body, "Radio or SDR",
                         lambda p: ttk.Combobox(p, textvariable=self.v["profile"], values=names, state="readonly",
                                                width=46),
                         lambda: self.radios.BY_NAME[self.v["profile"].get()].help())
        info = self._note("")

        def show(_e=None):
            p = self.radios.BY_NAME[self.v["profile"].get()]
            info.config(text=p.help() + ("\n\n" + ic9100_note(p.name) if ic9100_note(p.name) else ""))
        cb.bind("<<ComboboxSelected>>", lambda e: (show(), self._apply_profile()))
        show()

    def _apply_profile(self):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        if p.backend in ("hamlib", "hackrf"):
            self.v["backend"].set(p.backend)
        if p.usb_audio == "built-in" and p.backend == "hamlib":
            self.v["out"].set(self.ad.choices("out")[0])
            self.v["in"].set(self.ad.choices("in")[0])
        if "9100" in p.name:
            self.v["baud"].set("19200")
        for b in ("2m", "1.25m", "70cm"):
            if b not in p.bands:
                self.v["band_" + b].set(False)

    def p_connection(self):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        self._title("Connect the radio", "Switch the radio on and plug in its USB cable, then press Refresh.")
        self._field(self.body, "Transmit with",
                    lambda q: ttk.Combobox(q, textvariable=self.v["backend"], values=["dry-run", "hamlib", "hackrf"],
                                           state="readonly", width=14),
                    "dry-run: write WAV files only (safe for trying things).\nhamlib: control the radio through "
                    "its CAT port.\nhackrf: a HackRF One SDR.")

        def model_row(q):
            fr = ttk.Frame(q)
            ttk.Entry(fr, textvariable=self.v["model"], width=8).pack(side="left")
            b = ttk.Button(fr, text="Find", command=self._find)
            b.pack(side="left", padx=6)
            Tooltip(b, "Look your radio up in Hamlib's list (needs Hamlib installed).")
            return fr
        self._field(self.body, "Hamlib model no.", model_row, "Hamlib's number for your radio. Press Find.")
        ports = serial_ports()
        if not self.v["port"].get() and ports:
            cp = next((x for x in ports if "cp210" in x.lower() or "silicon labs" in x.lower()), ports[0])
            self.v["port"].set(cp)
        else:
            self.v["port"].set(port_label(port_from_label(self.v["port"].get()), ports))
        self.w_port = self._field(self.body, "CAT port",
                                  lambda q: ttk.Combobox(q, textvariable=self.v["port"], values=ports, width=46),
                                  "The radio's control port. The IC-9100 appears as 'Silicon Labs CP210x USB to "
                                  "UART Bridge (COMx)'.")
        self._field(self.body, "CAT speed",
                    lambda q: ttk.Combobox(q, textvariable=self.v["baud"], width=10,
                                           values=["4800", "9600", "19200", "38400", "57600", "115200"]),
                    "Must match the radio's CI-V / CAT baud rate (IC-9100: CI-V USB Baud Rate = 19200).")
        self.w_out = self._field(self.body, "Audio to radio (TX)",
                                 lambda q: ttk.Combobox(q, textvariable=self.v["out"], values=self.ad.choices("out"),
                                                        width=46),
                                 "Where Uranus plays its signal. ★ marks a radio's built-in USB codec.\n"
                                 + self.ad.CODEC_HELP)
        self.w_in = self._field(self.body, "Audio from radio (RX)",
                                lambda q: ttk.Combobox(q, textvariable=self.v["in"], values=self.ad.choices("in"),
                                                       width=46),
                                "Where Uranus hears the receiver, for decoding. Usually the same USB Audio CODEC.")
        bar = ttk.Frame(self.body)
        bar.pack(fill="x", pady=(10, 0))
        for text, cmd, tip in [("Refresh", self._refresh, "Look again for COM ports and sound devices."),
                               ("Start rigctld", self._rigctld, "Start Hamlib's rig server now, so the radio can be "
                                                                "controlled.")]:
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=(0, 8))
            Tooltip(b, tip)
        codec = self.ad.best_codec("out")
        if p.usb_audio == "built-in":
            self._note(("✔ Radio USB codec found: " + self.ad.spec_from_label(codec)) if codec else
                       "No USB Audio CODEC found yet. Check the radio is on, the USB cable is in and the radio's "
                       "USB driver is installed, then press Refresh. You can also pick it now and plug in later.",
                       C["green"] if codec else C["amber"])
        if ic9100_note(p.name):
            self._note(ic9100_note(p.name), C["muted"])

    def _refresh(self):
        ports = serial_ports()
        self.w_port.config(values=ports)
        self.w_out.config(values=self.ad.choices("out"))
        self.w_in.config(values=self.ad.choices("in"))
        if self.ad.best_codec("out") and not self.ad.is_codec(self.v["out"].get()):
            self.v["out"].set(self.ad.choices("out")[0])
            self.v["in"].set(self.ad.choices("in")[0])
        self.goto(self.i)

    def _find(self):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        if not p.hamlib_name:
            messagebox.showinfo("Hamlib", "This radio is not controlled through Hamlib.", parent=self)
            return
        num, msg = self.radios.find_hamlib_model(p.hamlib_name)
        if num:
            self.v["model"].set(str(num))
        else:
            messagebox.showinfo("Hamlib", msg, parent=self)

    def _rigctld(self):
        start_rigctld(self.app, self.v["model"].get(), port_from_label(self.v["port"].get()), self.v["baud"].get(),
                      self.cfg.get("radio", {}).get("rigctld_port", 4532))

    def p_bands(self):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        self._title("Bands", "The beacon visits each band in turn, with a 3-minute pause between bands.")
        tips = {"2m": "144-148 MHz: APRS 144.390, FT8 144.174, WSPR 144.490, Pumpkin.",
                "1.25m": "222-225 MHz: ITU Region 2 only. Needs a radio that covers 220 MHz (not the IC-9100).",
                "70cm": "420-450 MHz: FT8 432.174, WSPR 432.300, Pumpkin."}
        for b, label in (("2m", "2 m"), ("1.25m", "1.25 m (220 MHz)"), ("70cm", "70 cm")):
            c = ttk.Checkbutton(self.body, text=label, variable=self.v["band_" + b])
            c.pack(anchor="w", pady=4)
            if b not in p.bands:
                c.state(["disabled"])
                self.v["band_" + b].set(False)
            Tooltip(c, tips[b] + ("" if b in p.bands else f"\n{p.name} cannot use this band."))
        self._note("Check that your licence permits every frequency and unattended beacon operation. "
                   "Individual frequencies can be switched off in the settings file.", C["muted"])

    def p_psk(self):
        self._title("PSK Reporter", "Share the stations you decode on the worldwide PSK Reporter map, live.")
        c = ttk.Checkbutton(self.body, text="Upload my decodes to PSK Reporter", variable=self.v["psk"])
        c.pack(anchor="w", pady=4)
        Tooltip(c, "Every Pumpkin, UR or Cucumber station you decode while listening is reported, in batches "
                   "about every 5 minutes as PSK Reporter asks.")
        c2 = ttk.Checkbutton(self.body, text="Use the live server (leave unticked to test first)",
                             variable=self.v["psk_live"])
        c2.pack(anchor="w", pady=4)
        Tooltip(c2, "Unticked: PSK Reporter's test port, for checking your setup. Ticked: the public map.")
        self._field(self.body, "Contact e-mail (optional)",
                    lambda q: ttk.Entry(q, textvariable=self.v["contact"], width=30),
                    "PSK Reporter asks programs that look up spots to give a contact address. Optional; only "
                    "sent to PSK Reporter.")
        self._note("You can switch uploading on or off at any time from the PSK Reporter panel on the main "
                   "window, even while listening.", C["muted"])

    def p_finish(self):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        self._title("Ready to save", "Check the summary, then press Save and finish.")
        on = [n for b, n in (("2m", "2 m"), ("1.25m", "1.25 m"), ("70cm", "70 cm")) if self.v["band_" + b].get()]
        rows = [("Callsign / grid", f"{self.v['call'].get().upper()} · {self.v['grid'].get()}"),
                ("Power", self.v["power"].get()),
                ("Radio", p.name),
                ("Transmit with", self.v["backend"].get()),
                ("CAT", f"{port_from_label(self.v['port'].get()) or '-'} @ {self.v['baud'].get()} "
                        f"(Hamlib {self.v['model'].get() or '-'})"),
                ("Audio to radio", self.ad.spec_from_label(self.v["out"].get())),
                ("Audio from radio", self.ad.spec_from_label(self.v["in"].get())),
                ("Bands", " · ".join(on) or "none"),
                ("PSK Reporter", ("on, " + ("live" if self.v["psk_live"].get() else "test server"))
                 if self.v["psk"].get() else "off")]
        card = tk.Frame(self.body, bg=C["panel"], padx=16, pady=12)
        card.pack(fill="x")
        for k, val in rows:
            r = tk.Frame(card, bg=C["panel"])
            r.pack(fill="x", pady=2)
            tk.Label(r, text=k, bg=C["panel"], fg=C["muted"], width=18, anchor="w", font=(UI, 10)).pack(side="left")
            tk.Label(r, text=val, bg=C["panel"], fg=C["ink"], anchor="w", font=(UI, 10, "bold")).pack(side="left")
        self._note("Next: press 'Show plan', then 'Dry run'. Go ON AIR once the dry run looks right.", C["muted"])

    def finish(self):
        from . import geo
        grid = self.v["grid"].get().strip()
        g4 = grid[:2].upper() + grid[2:4]
        g6 = g4 + grid[4:6].lower() if len(grid) == 6 else ""
        lat, lon = geo.grid_to_latlon(g6 or g4)
        ch = {("station", "callsign"): self.v["call"].get().strip().upper(),
              ("station", "grid"): g4,
              ("station", "lat"): round(lat, 3), ("station", "lon"): round(lon, 3),
              ("station", "wspr_power_dbm"): int(self.v["power"].get().split()[0]),
              ("radio", "profile"): self.v["profile"].get(),
              ("radio", "backend"): self.v["backend"].get(),
              ("radio", "cat_port"): port_from_label(self.v["port"].get()),
              ("radio", "cat_baud"): int(self.v["baud"].get() or 19200),
              ("radio", "audio_device"): self.ad.spec_from_label(self.v["out"].get()),
              ("receive", "audio_device"): self.ad.spec_from_label(self.v["in"].get()),
              ("receive", "source"): "audio",
              ("reporting", "pskreporter"): self.v["psk"].get(),
              ("reporting", "pskreporter_test_server"): not self.v["psk_live"].get(),
              ("reporting", "pskreporter_contact"): self.v["contact"].get().strip()}
        if g6:
            ch[("station", "grid6")] = g6
        if self.v["model"].get().strip().isdigit():
            ch[("radio", "hamlib_model")] = int(self.v["model"].get())
        err = write_keys(ch, {b: self.v["band_" + b].get() for b in ("2m", "1.25m", "70cm")})
        if err:
            messagebox.showerror("Settings", err, parent=self)
            return
        self.app.print(f"\nSetup wizard saved your settings to {CONFIG}\n")
        self.app.refresh_station()
        self.app.set_state("ok", "Setup saved. Next: Show plan, then Dry run.")
        self.destroy()


class ChatWindow(tk.Toplevel):
    """Chat over Pumpkin or Cucumber, with hover help on every control."""

    DEFAULT_FREQ = {"PUMPKIN": "144.495", "CUCUMBER": "223.420"}

    def __init__(self, app):
        super().__init__(app)
        from . import chat as chatmod
        self.app, self.chatmod = app, chatmod
        self.title("Uranus - Chat")
        self.geometry("760x520")
        self.q = queue.Queue()
        self.engine = None
        top = ttk.Frame(self, padding=(10, 8))
        top.pack(fill="x")
        self.v_sub = tk.StringVar(value="PUMPKIN-15")
        cb = ttk.Combobox(top, textvariable=self.v_sub, values=chatmod.SUBMODES, state="readonly", width=13)
        ttk.Label(top, text="Mode").pack(side="left")
        cb.pack(side="left", padx=(4, 12))
        cb.bind("<<ComboboxSelected>>", lambda e: self.v_freq.set(self.DEFAULT_FREQ[self.v_sub.get().split("-")[0]]))
        Tooltip(cb, "PUMPKIN = SSB rig with GPS-locked oscillator, most sensitive.\n"
                    "CUCUMBER = any FM radio (squelch open, data port), no GPS needed.\n"
                    "-15: about 44 characters a minute. -60: about 11 a minute but about 6 dB more sensitive.\n"
                    "Both stations must choose the same mode.")
        self.v_freq = tk.StringVar(value="144.495")
        ttk.Label(top, text="MHz").pack(side="left")
        fe = ttk.Entry(top, textvariable=self.v_freq, width=10)
        fe.pack(side="left", padx=(4, 12))
        Tooltip(fe, "Channel (Cucumber) or dial frequency (Pumpkin). Agree it with the other station, and keep "
                    "clear of calling frequencies and beacon slots. 1.25 m: 223.420 FM simplex area.")
        self.v_slot = tk.StringVar(value="even")
        ttk.Label(top, text="I send in").pack(side="left")
        sl = ttk.Combobox(top, textvariable=self.v_slot, values=["even", "odd"], state="readonly", width=6)
        sl.pack(side="left", padx=(4, 4))
        ttk.Label(top, text="slots").pack(side="left", padx=(0, 12))
        Tooltip(sl, "Stations take turns like FT8: one sends in even slots and listens in odd ones, "
                    "the other the opposite way round.")
        self.bstart = ttk.Button(top, text="Start", command=self.start)
        self.bstart.pack(side="left", padx=3)
        Tooltip(self.bstart, "Tune the radio and start sending and listening in turn.")
        bstop = ttk.Button(top, text="Stop", command=self.stop)
        bstop.pack(side="left", padx=3)
        Tooltip(bstop, "Stop after the current slot.")
        bdemo = ttk.Button(top, text="Demo", command=self.demo)
        bdemo.pack(side="left", padx=3)
        Tooltip(bdemo, "Send the typed message through a simulated weak channel and decode it. No radio needed.")

        self.log = tk.Text(self, bg="#101418", fg="#e5e1d6", font=("Consolas", 10), wrap="word", height=18)
        self.log.tag_config("me", foreground="#f0a04b")
        self.log.tag_config("them", foreground="#7fd87f")
        self.log.tag_config("info", foreground="#8c98a4")
        self.log.pack(fill="both", expand=True, padx=10)
        bottom = ttk.Frame(self, padding=(10, 8))
        bottom.pack(fill="x")
        self.v_text = tk.StringVar()
        self.entry = ttk.Entry(bottom, textvariable=self.v_text)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self.send())
        Tooltip(self.entry, "Letters, digits, space and + - . / ? are sent. About 11 characters per transmission.")
        self.est = ttk.Label(bottom, text="", width=26)
        self.est.pack(side="left", padx=8)
        bsend = ttk.Button(bottom, text="Send", command=self.send)
        bsend.pack(side="left")
        Tooltip(bsend, "Queue the message. Your callsign is sent first, and again every 10 minutes.")
        self.v_text.trace_add("write", lambda *a: self.estimate())
        self.say("Choose a mode and frequency, agree slots with the other station, then Start.\n", "info")
        self.after(150, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def say(self, text, tag="info"):
        self.log.insert("end", text, tag)
        self.log.see("end")

    def estimate(self):
        n = len(self.chatmod.urmode.split_text(self.v_text.get()))
        per = int(self.v_sub.get().split("-")[1])
        self.est.config(text=f"{n} frame(s), about {n * 2 * per // 60} min {n * 2 * per % 60} s" if n else "")

    def on_event(self, e):
        self.q.put(e)

    def poll(self):
        try:
            while True:
                e = self.q.get_nowait()
                t = e.get("type")
                stamp = time.strftime("%H:%M:%S", time.gmtime())
                if t == "message":
                    self.say(f"{stamp}  {e['from']}: {e['text']}\n", "them")
                elif t == "frame":
                    snr = e.get("snr")
                    self.say(f"{stamp}  part {e['seq']}{'+' if e['more'] else ''} {e['text']!r}"
                             f"{'' if snr is None else f'  {snr:+.0f} dB'}\n", "info")
                elif t == "id":
                    self.say(f"{stamp}  heard {e['call']} {e['grid']}\n", "info")
                elif t == "tx":
                    self.say(f"{stamp}  sent {e['text']}\n", "me")
                elif t == "queued":
                    self.say(f"{stamp}  me: {e['text']}  ({e['frames']} frames, about {e['eta_s'] // 60} min)\n", "me")
                elif t == "lost":
                    self.say(f"{stamp}  NOT DECODED {e['text']}\n", "info")
                else:
                    self.say(f"{stamp}  {e.get('text', '')}\n", "info")
        except queue.Empty:
            pass
        self.after(150, self.poll)

    def _cfg(self):
        import tomllib
        with open(CONFIG, "rb") as f:
            return tomllib.load(f)

    def start(self):
        if self.engine:
            return
        try:
            cfg = self._cfg()
            freq = float(self.v_freq.get())
            rc = cfg["radio"]
            from .radio import DryRunRadio, HamlibRadio
            if rc.get("backend", "dry-run") == "dry-run":
                radio = DryRunRadio(os.path.join(BASE, "out"))
                self.say("Dry-run: transmissions are written to WAV files, nothing is sent.\n", "info")
            elif rc.get("backend") == "hackrf":
                from .sdr import HackRFRadio
                sd = cfg.get("sdr", {})
                radio = HackRFRadio(sd.get("hackrf_txvga", 10), sd.get("hackrf_amp", False))
            else:
                radio = HamlibRadio(rc["rigctld_host"], rc["rigctld_port"], rc.get("audio_device", "default"))
            self.engine = self.chatmod.ChatEngine(cfg, radio, self.v_sub.get(), freq,
                                                  0 if self.v_slot.get() == "even" else 1, self.on_event)
        except Exception as e:                # noqa: BLE001
            messagebox.showerror("Chat", f"Could not start: {e}")
            self.engine = None
            return
        threading.Thread(target=self.engine.run, daemon=True).start()

    def stop(self):
        if self.engine:
            self.engine.stop.set()
            self.engine = None
            self.say("Stopped.\n", "info")

    def send(self):
        text = self.v_text.get().strip()
        if not text:
            return
        if not self.engine:
            messagebox.showinfo("Chat", "Press Start first, or use Demo to try it without a radio.")
            return
        self.engine.send(text)
        self.v_text.set("")

    def demo(self):
        text = self.v_text.get().strip() or "8P5AB testing chat on 220"
        sub = self.v_sub.get()
        level = -6.0 if sub.startswith("CUCUMBER") else -20.0
        self.say(f"Demo: {sub} through a simulated channel at {level:+.0f} dB...\n", "info")

        def go():
            for e in self.chatmod.demo(text, sub, level):
                self.q.put(e)
        threading.Thread(target=go, daemon=True).start()

    def close(self):
        self.stop()
        self.destroy()


def _open(path):
    if os.name == "nt":
        os.startfile(path)                   # noqa: S606 - opens with the default app
    elif shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", path])
    else:
        print(path)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
