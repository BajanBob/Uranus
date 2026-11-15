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
BAND_EDGES = {"2m": (144.0, 148.0), "1.25m": (220.0, 225.0), "70cm": (420.0, 450.0)}

# Band-plan segments the entries below sit in (Region 2 / ARRL).
SEGMENTS = {
    "2m": [(144.100, 144.275, "weak-signal SSB/CW and digital (FT8 144.174)"),
           (144.275, 144.300, "propagation beacons (IARU Region 2)"),
           (144.300, 144.500, "ARRL 'new OSCAR' segment, used for WSPR 144.489"),
           (144.790, 144.810, "APRS (IARU Region 1 channel 144.800)"),
           (144.900, 145.100, "packet and digital data"),
           (145.500, 145.800, "FM simplex and digital (local option)")],
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
        return f"{self.mhz:.3f}  {self.status}{reg} · {self.note}"


PLAN = [
    # ------------------------------------------------------------ 2 m
    Freq("2m", "aprs", 144.390, "R2", "standard", "APRS, North America and the Caribbean"),
    Freq("2m", "aprs", 144.800, "R1", "standard", "APRS, Europe and Africa (Region 1 only)"),
    Freq("2m", "ft8", 144.174, "All", "standard", "FT8 calling (WSJT-X default)"),
    Freq("2m", "wspr", 144.489, "All", "standard", "WSPR, tones 144.4904-144.4906"),
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
    Freq("70cm", "aprs", 433.800, "R1", "standard", "APRS, Europe (Region 1 only)"),
    Freq("70cm", "aprs", 432.500, "R2", "proposed", "no Region 2 APRS standard; check local plan"),
    Freq("70cm", "cucumber", 433.500, "R2", "proposed", "FM data in 433-435 links/digital; agree locally"),
    Freq("70cm", "cucumber", 446.100, "R2", "proposed", "FM simplex area near 446.000 calling; check local plan"),
]

# Occupied bandwidth used for the edge check (kHz): SSB modes stay within 3 kHz of the dial,
# FM modes occupy a 12.5 kHz channel centred on the frequency.
_BW_KHZ = {"aprs": 12.5, "cucumber": 12.5, "ft8": 3.0, "wspr": 3.0, "pumpkin": 3.0, "ur": 3.0}
FM_MODES = ("aprs", "cucumber")


def options(band, mode, region="R2"):
    """Frequencies for this band and mode, the region's own first, then 'All', then other regions."""
    order = {region: 0, "All": 1}
    return sorted((f for f in PLAN if f.band == band and f.mode == mode),
                  key=lambda f: (order.get(f.region, 2), ["standard", "common", "proposed"].index(f.status)))


def find(band, mode, mhz):
    return next((f for f in PLAN if f.band == band and f.mode == mode and abs(f.mhz - mhz) < 0.0005), None)


def check(band, mode, mhz, region="R2"):
    """'' if fine, else a plain-English warning (outside the allocation, wrong region, no segment)."""
    lo, hi = BAND_EDGES.get(band, (0, 1e9))
    bw = _BW_KHZ.get(mode, 3.0) / 1000
    occ = (mhz - bw / 2, mhz + bw / 2) if mode in FM_MODES else (mhz, mhz + bw)
    if band == "1.25m" and region != "R2":
        return "1.25 m is allocated to amateurs in ITU Region 2 only."
    if occ[0] < lo or occ[1] > hi:
        return f"{mhz:.4f} MHz is outside the {lo:g}-{hi:g} MHz allocation for {band}."
    f = find(band, mode, mhz)
    if f and f.region not in ("All", region):
        return f"{mhz:.3f} MHz is a Region {f.region[1]} frequency; check your licence and local band plan."
    if not any(a <= mhz <= b for a, b, _ in SEGMENTS.get(band, [])):
        return (f"{mhz:.3f} MHz is not in a band-plan segment Uranus knows for {band}. It may still be legal: "
                "check your national band plan.")
    return ""


def segment(band, mhz):
    return next((n for a, b, n in SEGMENTS.get(band, []) if a <= mhz <= b), "")
