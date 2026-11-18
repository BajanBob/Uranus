"""Frequency lists for each band and mode, inside the ITU allocations and IARU band plans.

Every entry is a *dial* frequency in MHz (the radio's display; USB modes put
their tones about 1.5 kHz above it). Status:

  standard - the established worldwide or regional frequency (e.g. WSJT-X default)
  common   - widely used by groups of stations
  proposed - a Uranus suggestion inside the right band-plan segment; agree locally

National rules come first: a band plan is voluntary and national allocations
differ (Barbados: 222-225 MHz on 1.25 m). Check your licence before transmitting.

Sources: IARU Region 2 band plan (2020), ARRL VHF/UHF band plans, WSJT-X
default working frequencies, published WSPR and APRS practice.
"""

from dataclasses import dataclass

# ITU Region 2 amateur allocations (MHz). 1.25 m exists only in Region 2.
BAND_EDGES = {"160m": (1.8, 2.0), "80m": (3.5, 4.0), "60m": (5.3515, 5.3665), "40m": (7.0, 7.3),
              "30m": (10.1, 10.15), "20m": (14.0, 14.35), "17m": (18.068, 18.168), "15m": (21.0, 21.45),
              "12m": (24.89, 24.99), "10m": (28.0, 29.7), "6m": (50.0, 54.0),
              "2m": (144.0, 148.0), "1.25m": (220.0, 225.0), "70cm": (420.0, 450.0)}
HF_BANDS = ("160m", "80m", "60m", "40m", "30m", "20m", "17m", "15m", "12m", "10m", "6m")
BAND_NAMES = {b: b[:-1] + " m" for b in BAND_EDGES}
BAND_NAMES.update({"1.25m": "1.25 m", "70cm": "70 cm"})


def is_hf(mhz):
    """HF (and 6 m) frequencies, where APRS runs at 300 baud on USB instead of 1200 baud on FM."""
    return mhz < 30.0

# Band-plan segments the entries below sit in (Region 2 / ARRL).
_HF_DIGITAL = {      # narrow-band digital segments where WSPR, FT8 and HF packet operate (IARU Region 2)
    "160m": [(1.836, 1.843, "narrow-band digital (WSPR 1.8366, FT8 1.840)")],
    "80m": [(3.568, 3.600, "narrow-band digital (WSPR 3.5686, FT8 3.573)")],
    "60m": [(5.3515, 5.3665, "WRC-15 60 m allocation, all modes to 2.8 kHz (FT8 5.357, WSPR 5.3647)")],
    "40m": [(7.038, 7.080, "narrow-band digital (WSPR 7.0386, FT8 7.074)")],
    "30m": [(10.130, 10.150, "narrow-band digital (FT8 10.136, WSPR 10.1387, HF APRS 10.1476)")],
    "20m": [(14.070, 14.112, "narrow-band digital (FT8 14.074, WSPR 14.0956, HF packet 14.103)")],
    "17m": [(18.095, 18.109, "narrow-band digital (FT8 18.100, WSPR 18.1046)")],
    "15m": [(21.070, 21.110, "narrow-band digital (FT8 21.074, WSPR 21.0946)"),
            (21.130, 21.150, "narrow-band digital (FT4 21.140)")],
    "12m": [(24.915, 24.929, "narrow-band digital (FT8 24.915, WSPR 24.9246)")],
    "10m": [(28.070, 28.190, "narrow-band digital (FT8 28.074, WSPR 28.1246)")],
    "6m": [(50.280, 50.330, "weak-signal digital (WSPR 50.293, FT8 50.313)")],
}

SEGMENTS = {**_HF_DIGITAL, 
    "2m": [(144.100, 144.275, "weak-signal SSB/CW and digital (FT8 144.174)"),
           (144.275, 144.300, "propagation beacons (IARU Region 2)"),
           (144.300, 144.500, "ARRL 'new OSCAR' segment, used for WSPR 144.489"),
           (144.500, 144.794, "all-mode and digital (IARU Region 1 and 3 plans; APRS in NZ, Taiwan, Japan)"),
           (144.794, 144.990, "digital communications (IARU Region 1; APRS 144.800)"),
           (144.900, 145.100, "packet and digital data"),
           (145.100, 145.200, "digital and packet in some Region 3 plans (APRS 145.175, Australia)"),
           (145.500, 145.800, "FM simplex and digital (local option; APRS 145.570, Brazil)"),
           (145.800, 146.000, "amateur satellites (ISS and satellite APRS 145.825)")],
    "1.25m": [(222.000, 222.150, "weak-signal modes"),
              (222.050, 222.060, "propagation beacons"),
              (223.400, 223.520, "FM simplex"),
              (223.520, 223.640, "digital and packet")],
    "70cm": [(432.000, 432.100, "weak-signal CW/SSB, EME (calling 432.100)"),
             (432.100, 433.000, "mixed mode and weak-signal work (FT8 432.174)"),
             (432.300, 432.400, "propagation beacons (IARU Region 2 / ARRL)"),
             (433.000, 435.000, "auxiliary and repeater links, digital (check local plan)"),
             (445.000, 447.000, "FM simplex and links, local option (446.000 simplex calling)")],
}


@dataclass(frozen=True)
class Freq:
    band: str
    mode: str          # aprs, ft8, wspr, pumpkin, cucumber, ur
    mhz: float         # dial frequency
    region: str        # "All", "R2", "R1"
    status: str        # standard, common, proposed
    note: str

    def label(self):
        reg = "" if self.region == "All" else f" · {self.region}"
        return f"{fmt(self.mhz)}  {self.status}{reg} · {self.note}"


def fmt(mhz):
    """MHz with every significant digit: 144.390, 10.1476, 1.8366 (never rounded to 3 decimals)."""
    s = f"{mhz:.4f}"
    return s[:-1] if s.endswith("0") else s


PLAN = [
    # ------------------------------------------------------------ HF and 6 m (dial frequencies, USB)
    *[Freq(band, "ft8", mhz, "All", "standard", "FT8 (WSJT-X default)") for band, mhz in (
        ("160m", 1.840), ("80m", 3.573), ("60m", 5.357), ("40m", 7.074), ("30m", 10.136), ("20m", 14.074),
        ("17m", 18.100), ("15m", 21.074), ("12m", 24.915), ("10m", 28.074), ("6m", 50.313))],
    Freq("6m", "ft8", 50.323, "All", "common", "FT8, alternative 6 m frequency"),
    *[Freq(band, "ft4", mhz, "All", "standard", "FT4 (WSJT-X default)") for band, mhz in (
        ("80m", 3.575), ("40m", 7.0475), ("30m", 10.140), ("20m", 14.080), ("17m", 18.104), ("15m", 21.140),
        ("12m", 24.919), ("10m", 28.180), ("6m", 50.318), ("2m", 144.170))],
    *[Freq(band, "wspr", mhz, "All", "standard", "WSPR dial (tones 1.4-1.6 kHz above)") for band, mhz in (
        ("160m", 1.8366), ("80m", 3.5686), ("60m", 5.3647), ("40m", 7.0386), ("30m", 10.1387),
        ("20m", 14.0956), ("17m", 18.1046), ("15m", 21.0946), ("12m", 24.9246), ("10m", 28.1246),
        ("6m", 50.293))],
    *[Freq(band, "jt65", mhz, "All", "standard", "JT65 (WSJT-X default, receive)") for band, mhz in (
        ("160m", 1.838), ("80m", 3.570), ("40m", 7.076), ("30m", 10.138), ("20m", 14.076), ("17m", 18.102),
        ("15m", 21.076), ("12m", 24.917), ("10m", 28.076), ("6m", 50.310))],
    *[Freq(band, "jt9", mhz, "All", "standard", "JT9 (WSJT-X default, receive)") for band, mhz in (
        ("160m", 1.839), ("80m", 3.572), ("40m", 7.078), ("30m", 10.140), ("20m", 14.078), ("17m", 18.104),
        ("15m", 21.078), ("12m", 24.919), ("10m", 28.078))],
    *[Freq(band, "fst4w", mhz, "All", "common", "FST4W-120 shares the WSPR window (receive)") for band, mhz in (
        ("160m", 1.8366), ("80m", 3.5686), ("40m", 7.0386), ("30m", 10.1387), ("20m", 14.0956))],
    Freq("30m", "aprs", 10.1476, "All", "standard", "HF APRS, 300 baud, USB dial with 1600/1800 Hz tones"),
    Freq("20m", "aprs", 14.1016, "All", "common", "HF packet NET105 (centre 14.1033; '14.105 LSB'), 300 baud"),

    # ------------------------------------------------------------ 2 m
    Freq("2m", "aprs", 144.390, "R2", "standard", "APRS: North America, Caribbean, Colombia, Chile; "
                                                  "also Indonesia, Malaysia, Thailand"),
    Freq("2m", "aprs", 144.930, "R2", "standard", "APRS: Argentina, Uruguay"),
    Freq("2m", "aprs", 145.570, "R2", "standard", "APRS: Brazil"),
    Freq("2m", "aprs", 144.800, "R1", "standard", "APRS: Europe, South Africa, Russia"),
    Freq("2m", "aprs", 144.575, "R3", "standard", "APRS: New Zealand"),
    Freq("2m", "aprs", 144.640, "R3", "standard", "APRS: Taiwan (China is also listed)"),
    Freq("2m", "aprs", 144.660, "R3", "standard", "APRS: Japan"),
    Freq("2m", "aprs", 145.175, "R3", "standard", "APRS: Australia"),
    Freq("2m", "aprs", 145.825, "All", "standard", "APRS via the ISS and satellites (path ARISS), worldwide"),
    Freq("2m", "ft8", 144.174, "All", "standard", "FT8 calling (WSJT-X default)"),
    Freq("2m", "wspr", 144.489, "All", "standard", "WSPR, tones 144.4904-144.4906"),
    Freq("2m", "q65", 144.170, "All", "common", "Q65-60A weak-signal (tropo, rain scatter), shares the FT4 window"),
    Freq("2m", "pumpkin", 144.490, "All", "proposed", "tones at 144.4915, 800 Hz above the WSPR window"),
    Freq("2m", "pumpkin", 144.285, "R2", "proposed", "Region 2 beacon segment 144.275-144.300"),
    Freq("2m", "pumpkin", 144.171, "All", "proposed", "weak-signal digital, just below FT8"),
    Freq("2m", "ur", 144.490, "All", "proposed", "tones near 144.4915, clear of the WSPR window"),
    Freq("2m", "ur", 144.287, "R2", "proposed", "Region 2 beacon segment"),
    Freq("2m", "cucumber", 145.580, "R2", "proposed", "FM simplex / digital area; agree locally"),
    Freq("2m", "cucumber", 145.050, "All", "proposed", "packet and digital segment 144.90-145.10"),
    # ------------------------------------------------------------ 1.25 m (Region 2 only)
    Freq("1.25m", "ft8", 222.065, "R2", "standard", "FT8 (WSJT-X default)"),
    Freq("1.25m", "ft8", 222.080, "R2", "common", "FT8 and MSK144 (Pacific Northwest)"),
    Freq("1.25m", "wspr", 222.0535, "R2", "proposed", "no WSPR standard yet; beacon segment 222.050-222.060"),
    Freq("1.25m", "pumpkin", 222.055, "R2", "proposed", "beacon segment 222.050-222.060"),
    Freq("1.25m", "pumpkin", 222.130, "R2", "proposed", "weak-signal SSB, clear of 222.100 calling"),
    Freq("1.25m", "ur", 222.130, "R2", "proposed", "weak-signal SSB, clear of 222.100 calling"),
    Freq("1.25m", "aprs", 223.540, "R2", "proposed", "digital/packet segment 223.52-223.64; no APRS standard"),
    Freq("1.25m", "cucumber", 223.420, "R2", "proposed", "FM simplex segment 223.40-223.52"),
    Freq("1.25m", "cucumber", 223.580, "R2", "proposed", "digital/packet segment 223.52-223.64"),
    # ------------------------------------------------------------ 70 cm
    Freq("70cm", "ft8", 432.065, "All", "standard", "FT8 (WSJT-X default)"),
    Freq("70cm", "ft8", 432.174, "All", "common", "FT8, widely used (matches 144.174)"),
    Freq("70cm", "wspr", 432.300, "R2", "common", "WSPR, US groups; beacon segment"),
    Freq("70cm", "wspr", 432.489, "All", "common", "WSPR, used in VK; mirrors 144.489"),
    Freq("70cm", "pumpkin", 432.310, "R2", "proposed", "beacon segment 432.300-432.400, 10 kHz above WSPR"),
    Freq("70cm", "pumpkin", 432.171, "All", "proposed", "weak-signal digital, just below FT8"),
    Freq("70cm", "ur", 432.310, "R2", "proposed", "beacon segment"),
    Freq("70cm", "aprs", 432.500, "R1", "standard", "APRS on UHF: Europe (no Region 2 standard)"),
    Freq("70cm", "cucumber", 433.500, "R2", "proposed", "FM data in 433-435 links/digital; agree locally"),
    Freq("70cm", "cucumber", 446.100, "R2", "proposed", "FM simplex area near 446.000 calling; check local plan"),
]

# Occupied bandwidth used for the edge check (kHz): SSB modes stay within 3 kHz of the dial,
# FM modes occupy a 12.5 kHz channel centred on the frequency.
_BW_KHZ = {"jt65": 3.0, "jt9": 3.0, "fst4": 3.0, "fst4w": 3.0, "ft4": 3.0, "q65": 3.0, "aprs": 12.5, "cucumber": 12.5, "ft8": 3.0, "wspr": 3.0, "pumpkin": 3.0, "ur": 3.0}
FM_MODES = ("aprs", "cucumber")


def options(band, mode, region="R2"):
    """Frequencies for this band and mode, the region's own first, then 'All', then other regions."""
    order = {region: 0, "All": 1}
    return sorted((f for f in PLAN if f.band == band and f.mode == mode),
                  key=lambda f: (order.get(f.region, 2), {"mine": -1, "standard": 0, "common": 1}.get(f.status, 2)))


def find(band, mode, mhz):
    return next((f for f in PLAN if f.band == band and f.mode == mode and abs(f.mhz - mhz) < 0.0005), None)


def check(band, mode, mhz, region="R2"):
    """'' if fine, else a plain-English warning (outside the allocation, wrong region, no segment)."""
    lo, hi = BAND_EDGES.get(band, (0, 1e9))
    bw = _BW_KHZ.get(mode, 3.0) / 1000
    fm = mode in FM_MODES and not is_hf(mhz)            # HF APRS is 300 baud on USB
    top_khz = {"wspr": 1.6, "aprs": 2.0}.get(mode, bw * 1000)     # WSPR tones sit 1.4-1.6 kHz above the dial
    occ = (mhz - bw / 2, mhz + bw / 2) if fm else (mhz, mhz + top_khz / 1000)
    if band == "1.25m" and region != "R2":
        return "1.25 m is allocated to amateurs in ITU Region 2 only."
    if occ[0] < lo or occ[1] > hi:
        return f"{mhz:.4f} MHz is outside the {lo:g}-{hi:g} MHz allocation for {band}."
    f = find(band, mode, mhz)
    if f and f.region not in ("All", region):
        return f"{mhz:.3f} MHz is a Region {f.region[1]} frequency; check your licence and local band plan."
    if mode == "wspr":
        std = wspr_dial(band)
        if std and abs(mhz - std) > 0.00005:
            return (f"WSPR stations listen on {std:.4f} MHz dial. At {mhz:.4f} your tones fall "
                    f"{(mhz - std) * 1e6:+.0f} Hz outside the 200 Hz WSPR window, so nobody will decode them.")
    if band == "60m":
        return "60 m rules differ from country to country (channels, power, modes): check your licence."
    if not any(a <= mhz <= b for a, b, _ in SEGMENTS.get(band, [])):
        return (f"{mhz:.3f} MHz is not in a band-plan segment Uranus knows for {band}. It may still be legal: "
                "check your national band plan.")
    return ""


def wspr_dial(band):
    """The standard WSPR dial frequency for a band, or None."""
    return next((f.mhz for f in PLAN if f.band == band and f.mode == "wspr" and f.status == "standard"), None)


def segment(band, mhz):
    return next((n for a, b, n in SEGMENTS.get(band, []) if a <= mhz <= b), "")
