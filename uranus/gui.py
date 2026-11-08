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
            ("1. Edit settings", self.edit_config),
            ("2. Show plan", lambda: self.cli(["plan", "--cycles", "2"])),
            ("3. Dry run (1 cycle)", self.dry_run),
            ("ON AIR", self.on_air),
            ("Stop", self.stop),
        ]
        for text, cmd in buttons:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3)
        bar2 = ttk.Frame(self)
        bar2.pack(fill="x", padx=6)
        for text, cmd in [
            ("URC demo (-29 dB)", lambda: self.cli(["urc-loopback", "--submode", "URC-60", "--snr", "-29"])),
            ("UR demo (-19 dB)", lambda: self.cli(["ur-loopback", "--submode", "UR-15", "--snr", "-19"])),
            ("Link budget", lambda: self.cli(["link-budget", "--watts", "10", "--mhz", "144.49",
                                              "--km", "200", "--extra-loss", "25",
                                              "--tx-gain", "10", "--rx-gain", "13"])),
            ("Voyager check", lambda: self.cli(["link-budget", "--voyager"])),
            ("Open output folder", self.open_out),
        ]:
            ttk.Button(bar2, text=text, command=cmd).pack(side="left", padx=3, pady=3)

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

    def stop(self):
        if self.runner:
            self.runner.stop.set()
            self.set_status("Stopping after the current transmission...", "#fff3c4")
        elif self.worker:
            self.set_status("Waiting for the current task to finish...", "#fff3c4")

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
