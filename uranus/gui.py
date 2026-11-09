"""Uranus control window - the double-click front end (Uranus.exe on Windows).

Buttons run the same code as the command line, in a background thread,
with all output shown in the window.
"""

import contextlib
import io
import logging
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk


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


class Tooltip:
    """Hover help: shows `text` (or text()) after a short delay."""

    def __init__(self, widget, text, delay_ms=450):
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
        tk.Label(self.tip, text=txt, justify="left", wraplength=420, bg="#fffbe6", fg="#17212b",
                 relief="solid", borderwidth=1, padx=8, pady=6, font=("Segoe UI", 9)).pack()

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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Uranus - 2 m / 70 cm beacon")
        self.geometry("900x620")
        self.minsize(720, 480)
        self.q = queue.Queue()
        self.runner = None
        self.worker = None
        os.chdir(BASE)
        ensure_config()

        handler = logging.StreamHandler(_QueueWriter(self.q))
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=6)
        buttons = [
            ("0. Station setup", self.setup),
            ("1. Edit settings", self.edit_config),
            ("2. Show plan", lambda: self.cli(["plan", "--cycles", "2"])),
            ("3. Dry run (1 cycle)", self.dry_run),
            ("ON AIR", self.on_air),
            ("Stop", self.stop),
        ]
        tips = {
            "0. Station setup": "Pick your radio or SDR, audio devices, bands and CAT port from lists.",
            "1. Edit settings": "Open uranus.toml in your text editor for everything else (callsign, grid, position, power).",
            "2. Show plan": "Show the next two cycles of transmissions with times and frequencies. Nothing is sent.",
            "3. Dry run (1 cycle)": "Run one full cycle in real time, writing WAV files instead of transmitting.",
            "ON AIR": "Start the transmit schedule on the selected radio. Asks for confirmation first.",
            "Stop": "Stop after the current transmission or listening slot.",
        }
        for text, cmd in buttons:
            b = ttk.Button(bar, text=text, command=cmd)
            b.pack(side="left", padx=3)
            Tooltip(b, tips.get(text, ""))
        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", padx=6)
        for text, cmd in [
            ("Pumpkin demo (-29 dB)", lambda: self.cli(["pumpkin-loopback", "--submode", "PUMPKIN-60", "--snr", "-29"])),
            ("Cucumber demo (FM)", lambda: self.cli(["cucumber-loopback", "--submode", "CUCUMBER-15", "--cnr", "-8"])),
            ("UR demo (-19 dB)", lambda: self.cli(["ur-loopback", "--submode", "UR-15", "--snr", "-19"])),
            ("Link budget", lambda: self.cli(["link-budget", "--watts", "10", "--mhz", "144.49",
                                              "--km", "200", "--extra-loss", "25",
                                              "--tx-gain", "10", "--rx-gain", "13"])),
            ("400 km example", lambda: self.cli(["link-budget", "--example"])),
            ("Listen (decode)", self.listen),
            ("Station map", lambda: self.cli(["map", "--psk", "--open"])),
            ("Map demo", lambda: self.cli(["map", "--demo", "--open"])),
            ("Open output folder", self.open_out),
        ]:
            b = ttk.Button(bar2, text=text, command=cmd)
            b.pack(side="left", padx=3, pady=3)
            Tooltip(b, {
                "Pumpkin demo (-29 dB)": "Encode a PUMPKIN-60 frame, bury it 29 dB under the noise and decode it.",
                "Cucumber demo (FM)": "Send a CUCUMBER-15 frame through a simulated FM radio link 8 dB below the noise "
                                      "in the channel (voice would need +10 dB) and decode it.",
                "UR demo (-19 dB)": "The same test for the noncoherent UR-15 mode.",
                "Link budget": "Signal margin for every mode on a sample 200 km 2 m path.",
                "400 km example": "Signal margin on a reference 400 km beyond-horizon 2 m path.",
                "Listen (decode)": "Decode Pumpkin/UR from the rig or RTL-SDR every slot and log who you hear.",
                "Station map": "Map of stations heard and stations that heard you (PSK Reporter), by band.",
                "Map demo": "The station map with clearly labelled sample stations.",
                "Open output folder": "Open the folder with WAV files, spots and the map.",
            }.get(text, ""))

        self.status = tk.Label(self, text="Ready. Start with '1. Edit settings'.", anchor="w",
                               bg="#e8e8e8", padx=8, pady=6, font=("Segoe UI", 11, "bold"))
        self.status.pack(fill="x", padx=6, pady=4)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.text = tk.Text(frame, bg="#101418", fg="#9fe870", font=("Consolas", 10), wrap="word")
        sb = ttk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        self.print(f"Uranus folder: {BASE}\nSettings file: {CONFIG}\n\n")
        self.after(100, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ helpers
    def print(self, s):
        self.text.insert("end", s)
        self.text.see("end")

    def poll(self):
        try:
            while True:
                self.print(self.q.get_nowait())
        except queue.Empty:
            pass
        if self.worker and not self.worker.is_alive():
            self.worker = None
            self.runner = None
            self.set_status("Finished.", "#e8e8e8")
        self.after(100, self.poll)

    def set_status(self, msg, colour):
        self.status.config(text=msg, bg=colour)

    def busy(self):
        if self.worker:
            messagebox.showinfo("Busy", "Something is already running. Press Stop first.")
            return True
        return False

    def start(self, fn, status, colour="#fff3c4"):
        if self.busy():
            return
        self.set_status(status, colour)

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

    # ------------------------------------------------------------------ actions
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
        self.start(go, "DRY RUN in progress (nothing is transmitted). Press Stop to end.")

    def on_air(self):
        if not messagebox.askyesno(
                "Transmit?", "Start transmitting with the settings in uranus.toml?\n\n"
                "Check: rigctld running, backend = \"hamlib\", correct audio_device, "
                "PC clock accurate, and every enabled frequency permitted by your licence."):
            return

        def go():
            self.runner = self._runner(False)
            self.runner.run()
        self.print("\n> ON AIR\n")
        self.start(go, "ON AIR - transmitting on schedule. Press Stop to end.", "#ffb3b3")

    def listen(self):
        def go():
            from . import monitor, pskreporter, scheduler
            cfg, _ = scheduler.load_config(CONFIG)
            rc = cfg.get("reporting", {})
            rep = None
            if rc.get("pskreporter", False):
                rep = pskreporter.Reporter(cfg["station"]["callsign"], cfg["station"]["grid"],
                                           test=rc.get("pskreporter_test_server", True))
            self.runner = monitor.Listener(cfg, rep)
            try:
                self.runner.run()
            finally:
                if rep:
                    rep.flush()
        self.print("\n> listen: decoding Pumpkin from the rig; spots go to out/spots.jsonl\n")
        self.start(go, "LISTENING - decodes appear below. Press Stop to end.", "#cfe3ff")

    def stop(self):
        if self.runner:
            self.runner.stop.set()
            self.set_status("Stopping after the current transmission...", "#fff3c4")
        elif self.worker:
            self.set_status("Waiting for the current task to finish...", "#fff3c4")

    def setup(self):
        SetupWindow(self)

    def edit_config(self):
        self.print(f"\nOpening {CONFIG}\nSet callsign, grid, lat, lon and wspr_power_dbm, save, "
                   "then press '2. Show plan'.\n")
        _open(CONFIG)

    def open_out(self):
        out = os.path.join(BASE, "out")
        os.makedirs(out, exist_ok=True)
        _open(out)

    def on_close(self):
        if self.runner:
            self.runner.stop.set()
        self.destroy()


class SetupWindow(tk.Toplevel):
    """Station setup: radio/SDR, backend, CAT, audio, bands - all from lists, with hover help."""

    def __init__(self, app):
        super().__init__(app)
        from . import radios
        import tomllib
        self.app, self.radios = app, radios
        self.title("Uranus - Station setup")
        self.resizable(False, False)
        try:
            with open(CONFIG, "rb") as f:
                self.cfg = tomllib.load(f)
        except Exception as e:              # noqa: BLE001
            messagebox.showerror("Settings", f"Could not read {CONFIG}:\n{e}")
            self.destroy()
            return
        rc, rx, sd = self.cfg.get("radio", {}), self.cfg.get("receive", {}), self.cfg.get("sdr", {})
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both")
        self.v = {}
        row = [0]

        def add(label, widget, tip):
            lab = ttk.Label(f, text=label)
            lab.grid(row=row[0], column=0, sticky="e", padx=6, pady=4)
            widget.grid(row=row[0], column=1, sticky="we", padx=6, pady=4)
            Tooltip(lab, tip)
            Tooltip(widget, tip)
            row[0] += 1

        names = [p.name for p in radios.PROFILES]
        self.v["profile"] = tk.StringVar(value=rc.get("profile", names[0]) if rc.get("profile") in names else names[0])
        cb = ttk.Combobox(f, textvariable=self.v["profile"], values=names, state="readonly", width=46)
        add("Radio / SDR", cb, lambda: radios.BY_NAME[self.v["profile"].get()].help())
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_profile())
        self.info = tk.Label(f, text="", justify="left", wraplength=470, anchor="w", fg="#4a5560")
        self.info.grid(row=row[0], column=0, columnspan=3, sticky="we", padx=6, pady=(0, 8))
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

        ports = []
        try:
            import serial.tools.list_ports
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:                    # noqa: BLE001
            pass
        self.v["cat_port"] = tk.StringVar(value=rc.get("cat_port", ports[0] if ports else ""))
        add("CAT port", ttk.Combobox(f, textvariable=self.v["cat_port"], values=ports, width=20),
            "The rig's CAT (control) port: COM3 on Windows, /dev/ttyUSB0 or /dev/ttyACM0 on Linux/Pi.")
        self.v["cat_baud"] = tk.StringVar(value=str(rc.get("cat_baud", 19200)))
        add("CAT speed", ttk.Combobox(f, textvariable=self.v["cat_baud"], values=["4800", "9600", "19200", "38400", "57600", "115200"], width=20),
            "Must match the CI-V / CAT baud rate set in the radio's menu.")

        outs, ins = ["default"], ["default"]
        try:
            import sounddevice as sdv
            for i, d in enumerate(sdv.query_devices()):
                if d["max_output_channels"] > 0:
                    outs.append(f"{i}: {d['name']}")
                if d["max_input_channels"] > 0:
                    ins.append(f"{i}: {d['name']}")
        except Exception:                    # noqa: BLE001
            pass
        self.v["audio_out"] = tk.StringVar(value=str(rc.get("audio_device", "default")))
        add("Audio to radio (TX)", ttk.Combobox(f, textvariable=self.v["audio_out"], values=outs, width=46),
            "Sound output that feeds the radio: usually 'USB Audio CODEC' for Icom/Yaesu rigs, or your Digirig/SignaLink.")
        self.v["audio_in"] = tk.StringVar(value=str(rx.get("audio_device", "default")))
        add("Audio from radio (RX)", ttk.Combobox(f, textvariable=self.v["audio_in"], values=ins, width=46),
            "Sound input carrying the receiver's audio, for listen mode. Usually the same USB Audio CODEC.")
        self.v["source"] = tk.StringVar(value=rx.get("source", "audio"))
        add("Listen with", ttk.Combobox(f, textvariable=self.v["source"], values=["audio", "rtl_fm"], state="readonly", width=20),
            "audio: the rig (or SDR software) through a sound input.\nrtl_fm: an RTL-SDR dongle directly (needs the rtl-sdr tools).")

        bf = ttk.Frame(f)
        active = {b["name"]: b.get("active", True) for b in self.cfg.get("band", [])}
        band_tips = {"2m": "144-148 MHz. APRS 144.390, FT8 144.174, WSPR 144.490, Pumpkin.",
                     "1.25m": "222-225 MHz (220 MHz band). ITU Region 2 only; Barbados 222-225 MHz, check your licence. "
                              "Quiet noise floor; needs a transverter, a tri-band FM rig (APRS) or an SDR.",
                     "70cm": "420-450 MHz. FT8 432.174, WSPR 432.300, Pumpkin."}
        for b in ("2m", "1.25m", "70cm"):
            self.v["band_" + b] = tk.BooleanVar(value=bool(active.get(b, False)))
            c = ttk.Checkbutton(bf, text={"2m": "2 m", "1.25m": "1.25 m (220)", "70cm": "70 cm"}[b], variable=self.v["band_" + b])
            c.pack(side="left", padx=(0, 12))
            Tooltip(c, band_tips[b])
        add("Bands", bf, "Bands the beacon cycles through. Frequencies you disabled for licensing reasons stay disabled.")

        lo = next((b.get("transverter_lo_mhz", 0.0) for b in self.cfg.get("band", []) if b["name"] == "1.25m"), 0.0)
        self.v["lo"] = tk.StringVar(value=str(lo))
        add("1.25 m transverter LO (MHz)", ttk.Entry(f, textvariable=self.v["lo"], width=10),
            "0 if the radio tunes 222 MHz itself. With a transverter: 194 for a 28 MHz IF, 78 for a 144 MHz IF.")
        self.v["txvga"] = tk.StringVar(value=str(sd.get("hackrf_txvga", 10)))
        add("HackRF TX gain (dB)", ttk.Spinbox(f, from_=0, to=47, textvariable=self.v["txvga"], width=8),
            "0-47 dB. Start low and measure your output after the band-pass filter.")

        bb = ttk.Frame(f)
        bb.grid(row=row[0], column=0, columnspan=3, sticky="e", pady=(10, 0))
        for text, cmd, tip in [("Start rigctld", self.start_rigctld, "Start Hamlib's rig server with the model, port and speed above."),
                               ("Save", self.save, "Write these choices into uranus.toml (other settings are kept)."),
                               ("Close", self.destroy, "Close without saving.")]:
            b = ttk.Button(bb, text=text, command=cmd)
            b.pack(side="left", padx=4)
            Tooltip(b, tip)
        self.on_profile(initial=True)

    def on_profile(self, initial=False):
        p = self.radios.BY_NAME[self.v["profile"].get()]
        self.info.config(text=p.help().split("\n", 1)[1])
        if not initial:
            self.v["backend"].set({"hamlib": "hamlib", "hackrf": "hackrf"}.get(p.backend, self.v["backend"].get()))
            if p.backend == "rtl_fm":
                self.v["source"].set("rtl_fm")
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
        r = self.radios
        with open(CONFIG, encoding="utf-8") as fh:
            t = fh.read()
        dev = lambda s: s.split(":", 1)[0] if s[:1].isdigit() else s       # noqa: E731
        t = r.set_toml_key(t, "radio", "profile", self.v["profile"].get())
        t = r.set_toml_key(t, "radio", "backend", self.v["backend"].get())
        if self.v["hamlib_model"].get().strip().isdigit():
            t = r.set_toml_key(t, "radio", "hamlib_model", int(self.v["hamlib_model"].get()))
        t = r.set_toml_key(t, "radio", "cat_port", self.v["cat_port"].get())
        t = r.set_toml_key(t, "radio", "cat_baud", int(self.v["cat_baud"].get() or 19200))
        t = r.set_toml_key(t, "radio", "audio_device", dev(self.v["audio_out"].get()))
        t = r.set_toml_key(t, "receive", "audio_device", dev(self.v["audio_in"].get()))
        t = r.set_toml_key(t, "receive", "source", self.v["source"].get())
        t = r.set_toml_key(t, "sdr", "hackrf_txvga", int(float(self.v["txvga"].get() or 10)))
        for b in ("2m", "1.25m", "70cm"):
            t = r.set_band_active(t, b, self.v["band_" + b].get())
        try:
            lo = float(self.v["lo"].get() or 0)
        except ValueError:
            messagebox.showerror("Settings", "Transverter LO must be a number in MHz.")
            return
        t = self._set_band_key(t, "1.25m", "transverter_lo_mhz", lo)
        import tomllib
        try:
            tomllib.loads(t)
        except Exception as e:               # noqa: BLE001
            messagebox.showerror("Settings", f"Not saved - the result would not be valid:\n{e}")
            return
        with open(CONFIG, "w", encoding="utf-8") as fh:
            fh.write(t)
        self.app.print(f"\nSaved station setup to {CONFIG}\n")
        self.app.set_status("Station setup saved.", "#cdeccd")

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
        exe = shutil.which("rigctld")
        if not exe:
            messagebox.showerror("rigctld", "rigctld not found. Install Hamlib and add it to your PATH.")
            return
        model, port, baud = self.v["hamlib_model"].get().strip(), self.v["cat_port"].get().strip(), self.v["cat_baud"].get()
        if not (model.isdigit() and port):
            messagebox.showerror("rigctld", "Set the Hamlib model number and CAT port first.")
            return
        port_no = str(self.cfg.get("radio", {}).get("rigctld_port", 4532))
        subprocess.Popen([exe, "-m", model, "-r", port, "-s", baud, "-t", port_no])
        self.app.print(f"Started rigctld -m {model} -r {port} -s {baud} -t {port_no}\n")


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
