"""Sound devices: lists for the dropdowns, and finding the radio's USB codec.

Rigs such as the Icom IC-9100, IC-9700, IC-7300 and IC-705, the Yaesu FT-991A and
many Kenwoods contain a USB sound card that Windows calls "USB Audio CODEC"
(shown as "Speakers (USB Audio CODEC)" and "Microphone (USB Audio CODEC)").

Uranus saves the device *name*, not its number, because Windows renumbers
sound devices whenever something is plugged in. The name is looked up again
each time audio is played or recorded.
"""

import logging

log = logging.getLogger("uranus.audio")

CODEC_HINTS = ("usb audio codec",)
CODEC_TAG = "  ★ radio USB codec"
CODEC_PLACEHOLDER = "USB Audio CODEC"
CODEC_HELP = ("USB Audio CODEC is the sound card built into the Icom IC-9100, IC-9700, IC-7300 and IC-705, "
              "the Yaesu FT-991A and similar rigs. It appears once the radio is on, plugged in by USB and "
              "its USB driver (Icom: 'USB Driver' from icomjapan.com) is installed.")

# Host APIs in order of preference: MME is the most forgiving on Windows.
_HOSTAPI_ORDER = ("MME", "Windows DirectSound", "Windows WASAPI", "ALSA", "Core Audio", "JACK")


def is_codec(name):
    n = (name or "").lower()
    return any(h in n for h in CODEC_HINTS)


def list_devices():
    """All sound devices as dicts (index, name, hostapi, inputs, outputs). [] if unavailable."""
    try:
        import sounddevice as sd
        apis = [a["name"] for a in sd.query_hostapis()]
        return [{"index": i, "name": d["name"], "hostapi": apis[d["hostapi"]] if d["hostapi"] < len(apis) else "",
                 "inputs": d["max_input_channels"], "outputs": d["max_output_channels"]}
                for i, d in enumerate(sd.query_devices())]
    except Exception as e:                       # noqa: BLE001
        log.debug("no device list: %s", e)
        return []


def _rank(d):
    try:
        return _HOSTAPI_ORDER.index(d["hostapi"])
    except ValueError:
        return len(_HOSTAPI_ORDER)


def _of_kind(devs, kind):
    key = "outputs" if kind == "out" else "inputs"
    return [d for d in devs if d[key] > 0]


def choices(kind, devs=None):
    """Dropdown labels for 'out' (to the radio) or 'in' (from the radio).

    Radio USB codecs come first and are starred. Each name is listed once.
    If no codec is present, a 'USB Audio CODEC' entry is still offered, so an
    IC-9100 owner can choose it before the radio is plugged in.
    """
    devs = list_devices() if devs is None else devs
    seen, codecs, others = set(), [], []
    for d in sorted(_of_kind(devs, kind), key=_rank):
        if d["name"] in seen:
            continue
        seen.add(d["name"])
        (codecs if is_codec(d["name"]) else others).append(d["name"] + (CODEC_TAG if is_codec(d["name"]) else ""))
    if not codecs:
        codecs = [CODEC_PLACEHOLDER + CODEC_TAG + " (not detected yet)"]
    return codecs + ["default"] + others


def best_codec(kind, devs=None):
    """The label of the first radio codec in choices(kind), or None if none is plugged in."""
    first = choices(kind, devs)[0]
    return None if first.endswith("(not detected yet)") else first


def spec_from_label(label):
    """What to save in uranus.toml for a dropdown label."""
    s = (label or "default").strip()
    if s.endswith("(not detected yet)"):
        return CODEC_PLACEHOLDER
    if CODEC_TAG in s:
        s = s.split(CODEC_TAG)[0]
    if ":" in s and s.split(":", 1)[0].strip().isdigit():     # old "3: name" style
        s = s.split(":", 1)[1].strip()
    return s or "default"


def label_for(spec, kind, devs=None):
    """The dropdown label that matches a saved value (for showing current settings)."""
    spec = str(spec or "default")
    if spec == "default":
        return "default"
    for c in choices(kind, devs):
        if spec_from_label(c).lower() == spec.lower():
            return c
    for c in choices(kind, devs):
        if spec.lower() in spec_from_label(c).lower():
            return c
    return spec


def resolve(spec, kind, devs=None):
    """Device index for sounddevice from a saved value; None means the system default.

    Accepts a number (old configs), an exact name, or part of a name such as
    'USB Audio CODEC'. Prefers MME on Windows when the name appears in several host APIs.
    """
    if spec in (None, "", "default"):
        return None
    if str(spec).isdigit():
        return int(spec)
    want = str(spec).strip().lower()
    cands = sorted(_of_kind(list_devices() if devs is None else devs, kind), key=_rank)
    for test in (lambda n: n == want, lambda n: want in n,
                 lambda n: is_codec(want) and is_codec(n)):
        for d in cands:
            if test(d["name"].strip().lower()):
                return d["index"]
    raise RuntimeError(f"sound device '{spec}' not found. Is the radio switched on and plugged in by USB? "
                       "Choose it again in Station setup.")
