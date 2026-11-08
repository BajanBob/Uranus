#!/usr/bin/env python3
"""
WhisperMite Setup - a simple window for uploading settings to a
Kanga WhisperMite WSPR beacon over USB.

Works on Windows, Mac and Raspberry Pi.
Needs:  pip install pyserial      (Pi: sudo apt install python3-serial python3-tk)
Run:    python whispermite_gui.py
"""

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    tk.Tk().withdraw()
    messagebox.showerror("pyserial missing",
                         "Install it first:\n\n  pip install pyserial\n\n"
                         "(Raspberry Pi: sudo apt install python3-serial)")
    raise SystemExit(1)

import sys
_BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(_BASE, "whispermite_settings.json")
PROMPT = re.compile(r"press\s+button", re.I)
VALID_DBM = [0, 3, 7, 10, 13, 17, 20, 23, 27, 30, 33, 37, 40, 43, 47, 50, 53, 57, 60]
FREQS = {"60m": "5.3662", "40m": "7.0401", "30m": "10.1402", "20m": "14.0971",
         "15m": "21.0961", "12m": "24.9261", "10m": "28.1261"}
DEFAULTS = {"callsign": "", "locator": "GK03", "power": "23",
            "f1": "7.0401", "f2": "5.3662", "band": "DUAL", "interval": "10",
            "baud": "9600", "line_end": "CR+LF"}
EOL = {"CR+LF": "\r\n", "CR": "\r", "LF": "\n"}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WhisperMite Setup")
        self.geometry("820x640")
        self.minsize(700, 520)
        self.ser = None
        self.rx = queue.Queue()
        self.stop_reader = threading.Event()
        self.rxbuf = ""
        self.busy = False
        self.vars = {k: tk.StringVar(value=v) for k, v in DEFAULTS.items()}
        self.vars["port"] = tk.StringVar()
        self.load_settings()
        self.build()
        self.refresh_ports()
        self.after(50, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ layout
    def build(self):
        pad = {"padx": 6, "pady": 4}

        # Connection row
        top = ttk.LabelFrame(self, text="1. Connect")
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Port").pack(side="left", padx=4)
        self.port_box = ttk.Combobox(top, textvariable=self.vars["port"], width=28)
        self.port_box.pack(side="left", padx=4)
        ttk.Button(top, text="↻", width=3, command=self.refresh_ports).pack(side="left")
        ttk.Label(top, text="Baud").pack(side="left", padx=(12, 4))
        ttk.Combobox(top, textvariable=self.vars["baud"], width=8, state="readonly",
                     values=["9600", "19200", "38400", "57600", "115200"]).pack(side="left")
        ttk.Label(top, text="Line end").pack(side="left", padx=(12, 4))
        ttk.Combobox(top, textvariable=self.vars["line_end"], width=7, state="readonly",
                     values=list(EOL)).pack(side="left")
        self.conn_btn = ttk.Button(top, text="Connect", command=self.toggle_connect)
        self.conn_btn.pack(side="right", padx=6)

        # Status banner
        self.status = tk.Label(self, text="Not connected", font=("Helvetica", 14, "bold"),
                               bg="#e5e5e5", fg="#333", pady=8)
        self.status.pack(fill="x", **pad)

        # Settings form
        form = ttk.LabelFrame(self, text="2. Your WSPR settings")
        form.pack(fill="x", **pad)
        row = 0

        def field(label, key, widget=None, col=0, hint=""):
            ttk.Label(form, text=label).grid(row=row, column=col, sticky="e", padx=4, pady=3)
            w = widget or ttk.Entry(form, textvariable=self.vars[key], width=12)
            w.grid(row=row, column=col + 1, sticky="w", padx=4, pady=3)
            if hint:
                ttk.Label(form, text=hint, foreground="#777").grid(row=row, column=col + 2,
                                                                   sticky="w", padx=2)

        field("Callsign", "callsign", hint="max 6, no /")
        field("Locator", "locator", col=3, hint="4 chars")
        row += 1
        field("Power dBm", "power", ttk.Combobox(form, textvariable=self.vars["power"], width=9,
                                                 values=[str(v) for v in VALID_DBM]),
              hint="200 mW = 23")
        field("Interval (min)", "interval", col=3, hint="even number")
        row += 1
        freq_hint = "  ".join(f"{b}={f}" for b, f in FREQS.items())
        field("F1 MHz", "f1")
        field("F2 MHz", "f2", col=3)
        row += 1
        ttk.Label(form, text=freq_hint, foreground="#777").grid(row=row, column=0, columnspan=6,
                                                               sticky="w", padx=6)
        row += 1
        field("Band", "band", ttk.Combobox(form, textvariable=self.vars["band"], width=9,
                                           state="readonly", values=["1", "2", "DUAL"]),
              hint="DUAL alternates F1/F2")

        # Action buttons
        act = ttk.LabelFrame(self, text="3. Send to the WhisperMite (after pressing Sync to enter setup)")
        act.pack(fill="x", **pad)
        self.action_btns = []
        for text, cmd in [("Upload settings", self.upload),
                          ("Show settings ( ? )", lambda: self.send_cmd("?")),
                          ("Toggle random shift ( R )", lambda: self.send_cmd("R")),
                          ("Save & exit ( X )", lambda: self.send_cmd("X"))]:
            b = ttk.Button(act, text=text, command=cmd)
            b.pack(side="left", padx=4, pady=4)
            self.action_btns.append(b)

        # Terminal
        term = ttk.LabelFrame(self, text="Terminal")
        term.pack(fill="both", expand=True, **pad)
        self.text = tk.Text(term, height=12, bg="#111", fg="#7CFC00", insertbackground="white",
                            font=("Courier", 10), wrap="word")
        sb = ttk.Scrollbar(term, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(fill="both", expand=True)
        entry_row = ttk.Frame(term)
        entry_row.pack(fill="x")
        self.entry = ttk.Entry(entry_row)
        self.entry.pack(side="left", fill="x", expand=True, padx=2, pady=2)
        self.entry.bind("<Return>", lambda e: self.send_typed())
        ttk.Button(entry_row, text="Send", command=self.send_typed).pack(side="right")

    # ------------------------------------------------------------------ settings file
    def load_settings(self):
        try:
            with open(SETTINGS_FILE) as f:
                for k, v in json.load(f).items():
                    if k in self.vars:
                        self.vars[k].set(v)
        except (OSError, ValueError):
            pass

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump({k: v.get() for k, v in self.vars.items()}, f, indent=2)
        except OSError:
            pass

    # ------------------------------------------------------------------ serial
    def refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        # Put CH340 (the WhisperMite's USB chip) first
        ch340 = [p.device for p in serial.tools.list_ports.comports()
                 if (p.vid == 0x1A86) or "CH34" in (p.description or "")]
        ports = ch340 + [p for p in ports if p not in ch340]
        self.port_box["values"] = ports
        if ports and self.vars["port"].get() not in ports:
            self.vars["port"].set(ports[0])
        if not ports:
            self.set_status("No USB device found – check cable (must be a DATA cable) "
                            "and CH340 driver", "#f7d4d4")

    def toggle_connect(self):
        if self.ser:
            self.disconnect()
            return
        port = self.vars["port"].get()
        if not port:
            messagebox.showwarning("No port", "Choose the WhisperMite's port first.")
            return
        try:
            self.ser = serial.Serial(port, int(self.vars["baud"].get()), timeout=0.1)
        except serial.SerialException as e:
            messagebox.showerror("Can't open port", str(e))
            self.ser = None
            return
        self.save_settings()
        self.rxbuf = ""
        self.stop_reader.clear()
        threading.Thread(target=self.reader, daemon=True).start()
        self.conn_btn.config(text="Disconnect")
        self.log(f"--- Connected to {port}. The WhisperMite is restarting... ---\n")
        self.set_status("Restarting… wait for the PRESS SYNC message (don't touch the button yet)",
                        "#fff3c4")

    def disconnect(self):
        self.stop_reader.set()
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser = None
        self.conn_btn.config(text="Connect")
        self.set_status("Disconnected", "#e5e5e5")

    def reader(self):
        while not self.stop_reader.is_set():
            try:
                data = self.ser.read(256)
            except Exception as e:  # unplugged
                self.rx.put(("error", str(e)))
                return
            if data:
                self.rx.put(("data", data.decode("ascii", errors="replace")))

    def poll(self):
        try:
            while True:
                kind, payload = self.rx.get_nowait()
                if kind == "error":
                    self.log(f"\n--- Connection lost: {payload} ---\n")
                    self.disconnect()
                elif kind == "data":
                    self.log(payload)
                    self.rxbuf = (self.rxbuf + payload)[-400:]
                    if PROMPT.search(self.rxbuf):
                        self.rxbuf = ""
                        self.set_status("▶ PRESS THE SYNC BUTTON NOW ◀", "#ff6b6b")
                        self.bell()
                        self.after(6000, self.after_prompt)
                elif kind == "status":
                    self.set_status(*payload)
        except queue.Empty:
            pass
        self.after(50, self.poll)

    def after_prompt(self):
        if self.ser:
            self.set_status("If the menu appeared below, click 'Upload settings'. "
                            "(Menu closes after 60 s idle – reconnect if it does.)", "#cdeccd")

    def log(self, s):
        self.text.insert("end", s.replace("\r\n", "\n").replace("\r", "\n"))
        self.text.see("end")

    def set_status(self, msg, colour):
        self.status.config(text=msg, bg=colour)

    # ------------------------------------------------------------------ sending
    def write_line(self, line):
        self.ser.write((line + EOL[self.vars["line_end"].get()]).encode("ascii"))
        self.rx.put(("data", f"\n> {line}\n"))

    def send_cmd(self, line):
        if not self.ser:
            messagebox.showinfo("Not connected", "Click Connect first.")
            return
        self.write_line(line)

    def send_typed(self):
        line = self.entry.get().strip()
        if line:
            self.send_cmd(line)
            self.entry.delete(0, "end")

    def validate(self):
        v = {k: self.vars[k].get().strip().upper() for k in DEFAULTS}
        errs = []
        if not re.fullmatch(r"[A-Z0-9]{3,6}", v["callsign"]):
            errs.append("Callsign: 3–6 letters/digits, no '/'")
        if not re.fullmatch(r"[A-R]{2}[0-9]{2}", v["locator"]):
            errs.append("Locator: 4 characters like GK03")
        if not v["power"].isdigit() or int(v["power"]) not in VALID_DBM:
            errs.append("Power must be a WSPR dBm value (e.g. 23)")
        if not v["interval"].isdigit() or int(v["interval"]) < 2 or int(v["interval"]) % 2:
            errs.append("Interval must be an even number of minutes")
        for k in ("f1", "f2"):
            try:
                float(v[k])
            except ValueError:
                errs.append(f"{k.upper()} must be a frequency in MHz, e.g. 7.0401")
        if errs:
            messagebox.showerror("Please fix", "\n".join(errs))
            return None
        return v

    def upload(self):
        if not self.ser:
            messagebox.showinfo("Not connected", "Click Connect first, then press Sync when asked.")
            return
        if self.busy:
            return
        v = self.validate()
        if not v:
            return
        self.save_settings()
        cmds = [f"Q {v['callsign']} {v['locator']} {v['power']}",
                f"F1 {float(v['f1']):.4f}", f"F2 {float(v['f2']):.4f}",
                f"B {v['band']}", f"I {v['interval']}", "?"]

        def worker():
            self.busy = True
            self.rx.put(("status", ("Uploading…", "#fff3c4")))
            try:
                for c in cmds:
                    self.write_line(c)
                    time.sleep(1.2)
                self.rx.put(("status", ("Uploaded. Check the '?' listing, then click "
                                        "'Save & exit ( X )'.", "#cdeccd")))
            except Exception as e:
                self.rx.put(("status", (f"Upload failed: {e}", "#f7d4d4")))
            finally:
                self.busy = False

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self):
        self.save_settings()
        if self.ser:
            self.disconnect()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
