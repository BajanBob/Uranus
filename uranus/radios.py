"""Radio and SDR profiles shown in the Station setup window.

Each profile says what the equipment can do for Uranus: bands, whether it
transmits SSB (needed for FT8/WSPR/UR/URC) or FM only (APRS), whether it has a
built-in USB sound card, and which Uranus backend drives it. `hamlib_name`
is matched against `rigctl -l` to find the Hamlib model number, so no model
numbers are hard-coded. Specifications change between model years and
regional versions: always confirm against the radio's manual.
"""

from dataclasses import dataclass, field


@dataclass
class Profile:
    name: str
    kind: str                  # transceiver, handheld, mobile, transverter, sdr-rx, sdr-trx, generic
    bands: list                # of "2m", "1.25m", "70cm"
    ssb: bool                  # can transmit USB/SSB (FT8, WSPR, UR, URC)
    usb_audio: str             # "built-in", "external interface", "n/a"
    backend: str               # hamlib, hackrf, rtl_fm, audio-only
    hamlib_name: str = ""
    notes: str = ""
    tags: list = field(default_factory=list)

    def help(self):
        bands = ", ".join({"2m": "2 m", "1.25m": "1.25 m (220 MHz)", "70cm": "70 cm"}[b] for b in self.bands)
        if self.kind == "sdr-rx":
            modes = "Receive only: decodes URC/UR (and feeds WSJT-X) but cannot transmit"
        else:
            modes = "SSB modes (FT8, WSPR, UR, URC) and FM (APRS)" if self.ssb else "FM only: APRS, not the SSB weak-signal modes"
        audio = {"built-in": "Built-in USB sound card and CAT over one cable.",
                 "external interface": "Needs an audio interface (e.g. Digirig Mobile or SignaLink USB) for data.",
                 "n/a": "Audio is produced in software (SDR)."}[self.usb_audio]
        return f"{self.name}\nBands: {bands}\nModes: {modes}\n{audio}\nUranus backend: {self.backend}.\n{self.notes}".strip()


PROFILES = [
    Profile("Generic CAT rig with USB audio", "generic", ["2m", "70cm"], True, "built-in", "hamlib", "",
            "Any Hamlib-supported all-mode rig. Choose this if your radio is not listed."),
    # ---- all-mode transceivers (SSB) ----
    Profile("Icom IC-9700", "transceiver", ["2m", "70cm"], True, "built-in", "hamlib", "IC-9700",
            "All-mode 2 m / 70 cm / 23 cm base station. Excellent for URC; accepts a 10 MHz GPS reference "
            "for frequency lock, which URC needs at both ends. No 1.25 m."),
    Profile("Icom IC-705", "transceiver", ["2m", "70cm"], True, "built-in", "hamlib", "IC-705",
            "Portable HF to 70 cm, 10 W. Also a good IF rig for a 222 MHz transverter."),
    Profile("Icom IC-905", "transceiver", ["2m", "70cm"], True, "built-in", "hamlib", "IC-905",
            "2 m / 70 cm / 23 cm and microwave all-mode with GPS-disciplined option. Check USB audio "
            "setup in its manual."),
    Profile("Yaesu FT-991A", "transceiver", ["2m", "70cm"], True, "built-in", "hamlib", "FT-991",
            "HF / 6 m / 2 m / 70 cm all-mode with built-in USB sound card. No 1.25 m."),
    Profile("Yaesu FT-818ND", "transceiver", ["2m", "70cm"], True, "external interface", "hamlib", "FT-818",
            "Portable HF to 70 cm, 6 W. Needs a Digirig or similar for audio."),
    Profile("Kenwood TS-2000", "transceiver", ["2m", "70cm"], True, "external interface", "hamlib", "TS-2000",
            "HF / 6 m / 2 m / 70 cm all-mode (23 cm option). Needs an audio interface."),
    # ---- 1.25 m (220 MHz) capable, FM ----
    Profile("Kenwood TH-D75A (US)", "handheld", ["2m", "1.25m", "70cm"], False, "external interface", "audio-only", "",
            "Tri-band handheld with built-in APRS. US version transmits FM on 222 MHz. SSB is receive only, "
            "so use it for 1.25 m APRS, not for URC transmit."),
    Profile("Kenwood TH-D74A (US)", "handheld", ["2m", "1.25m", "70cm"], False, "external interface", "audio-only", "",
            "Earlier tri-band APRS handheld, 5 W on 222 MHz in the US version. FM transmit only."),
    Profile("Yaesu VX-6R / VX-7R (US)", "handheld", ["2m", "1.25m", "70cm"], False, "external interface", "audio-only", "",
            "Tri-band FM handhelds; low power on 222 MHz. APRS via an audio interface."),
    Profile("Alinco DR-235T", "mobile", ["1.25m"], False, "external interface", "audio-only", "",
            "222 MHz FM mobile (about 25 W). Good for 1.25 m APRS with an interface on its data/mic port."),
    Profile("AnyTone AT-D578UV III Plus (220 version)", "mobile", ["2m", "1.25m", "70cm"], False,
            "external interface", "audio-only", "",
            "Tri-band FM/DMR mobile; transmit on 222 MHz only in versions sold for Region 2. FM APRS only."),
    Profile("BTECH UV-5X3", "handheld", ["2m", "1.25m", "70cm"], False, "external interface", "audio-only", "",
            "Low-cost tri-band FM handheld. Fine for experiments; check spurious emissions before long use."),
    # ---- 222 MHz transverters (SSB on 1.25 m) ----
    Profile("222 MHz transverter + all-mode IF rig", "transverter", ["1.25m"], True, "built-in", "hamlib", "",
            "e.g. Elecraft XV222, Downeast Microwave or Q5Signal 222 transverters with an IF rig such as the "
            "IC-705. Set transverter_lo_mhz on the 1.25 m band (194 for a 28 MHz IF, 78 for a 144 MHz IF)."),
    # ---- SDRs ----
    Profile("HackRF One (SDR transmit, experimental)", "sdr-trx", ["2m", "1.25m", "70cm"], True, "n/a", "hackrf", "",
            "Transmits SSB or FM I/Q directly. Milliwatts only, strong harmonics: MUST be followed by a "
            "band-pass filter, normally an amplifier. Uranus keeps its gain low by default."),
    Profile("RTL-SDR v3 / v4 (receive only)", "sdr-rx", ["2m", "1.25m", "70cm"], False, "n/a", "rtl_fm", "",
            "Cheap receive-only dongle for listen mode (source = rtl_fm). Use a TCXO model and set rtl_ppm; "
            "URC needs the frequency within about 0.6 Hz, so a GPS-locked SDR is better for URC-60."),
    Profile("ADALM-Pluto (SDR)", "sdr-trx", ["70cm"], True, "n/a", "audio-only", "",
            "Official range 325 MHz to 3.8 GHz, so 70 cm out of the box; 2 m and 1.25 m need the widely "
            "used range extension. Not yet driven directly by Uranus: use it through SDR software with a "
            "virtual audio cable."),
    Profile("SDRplay RSP1B / RSPdx (receive)", "sdr-rx", ["2m", "1.25m", "70cm"], False, "n/a", "audio-only", "",
            "Receive with SDRuno or SDRconnect in USB mode and route the audio to Uranus through a "
            "virtual audio cable."),
    Profile("Airspy R2 / Mini (receive)", "sdr-rx", ["2m", "1.25m", "70cm"], False, "n/a", "audio-only", "",
            "Receive with SDR# in USB mode and route the audio to Uranus through a virtual audio cable."),
]

BY_NAME = {p.name: p for p in PROFILES}


def find_hamlib_model(name):
    """Look up a Hamlib model number by name in `rigctl -l`. Returns (number, line) or (None, reason)."""
    import shutil
    import subprocess
    exe = shutil.which("rigctl")
    if not exe:
        return None, "rigctl not found: install Hamlib"
    out = subprocess.run([exe, "-l"], capture_output=True, text=True, timeout=20).stdout
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit() and name.lower() in line.lower():
            return int(parts[0]), line.strip()
    return None, f"'{name}' not in rigctl -l"


def set_toml_key(text, section, key, value):
    """Set `key = value` inside [section] of a TOML file's text, keeping comments and layout."""
    import re
    val = f'"{value}"' if isinstance(value, str) else ("true" if value is True else "false" if value is False else str(value))
    lines = text.splitlines(keepends=True)
    start = None
    head = re.compile(rf"^\s*\[{re.escape(section)}\]\s*(#.*)?$")
    for i, ln in enumerate(lines):
        if head.match(ln.rstrip("\n")):
            start = i
            break
    if start is None:
        return text.rstrip("\n") + f"\n\n[{section}]\n{key} = {val}\n"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("["):
            end = j
            break
    pat = re.compile(rf"^(\s*){re.escape(key)}\s*=\s*(\"[^\"]*\"|[^#\n]*?)(\s*#.*)?$")
    for j in range(start + 1, end):
        m = pat.match(lines[j].rstrip("\n"))
        if m:
            lines[j] = f"{m.group(1)}{key} = {val}{m.group(3) or ''}\n"
            return "".join(lines)
    lines.insert(start + 1, f"{key} = {val}\n")
    return "".join(lines)


def set_band_active(text, band, active):
    """Switch a whole [[band]] block on or off (its `active` key). Slot-level
    `enabled` flags are left alone, so frequencies disabled for licensing
    reasons stay disabled."""
    out, in_band = [], False
    for ln in text.splitlines(keepends=True):
        s = ln.strip()
        if s == "[[band]]":
            in_band = False
        elif s.startswith("[[band.slot]]"):
            in_band = False if in_band == "done" else in_band
        if s.startswith("name =") and s.split("=", 1)[1].split("#")[0].strip().strip('"') == band:
            in_band = True
        elif in_band is True and s.startswith("active ="):
            indent = ln[:len(ln) - len(ln.lstrip())]
            comment = ("  " + ln[ln.index("#"):].rstrip("\n")) if "#" in ln else ""
            ln = f"{indent}active = {'true' if active else 'false'}{comment}\n"
            in_band = "done"
        out.append(ln)
    return "".join(out)
