# Frequencies for each band and mode

These are the lists behind **Bands and modes** and the Receiver's dial dropdown in Uranus. All are *dial* frequencies in MHz: for USB modes (FT8, WSPR, Pumpkin, UR) the tones sit about 1.5 kHz above the dial; for FM modes (APRS, Cucumber) it is the channel centre.

- **standard**: the established frequency (for FT8, the WSJT-X default).
- **common**: widely used by groups of stations.
- **proposed**: a Uranus suggestion inside the right band-plan segment. Agree it with local stations first.

Every entry is checked automatically to be inside the ITU Region 2 allocation and inside a known IARU Region 2 / ARRL band-plan segment. Band plans are voluntary and national rules differ: **your licence comes first.**

## 2 m (144-148 MHz)

| Mode | Dial MHz | Region | Status | Notes | Band-plan segment |
|---|---|---|---|---|---|
| APRS | 144.39 | R2 | standard | APRS: North America, Caribbean, Colombia, Chile; also Indonesia, Malaysia, Thailand | ARRL 'new OSCAR' segment, used for WSPR 144.489 |
| APRS | 144.575 | R3 | standard | APRS: New Zealand | all-mode and digital (IARU Region 1 and 3 plans; APRS in NZ, Taiwan, Japan) |
| APRS | 144.64 | R3 | standard | APRS: Taiwan (China is also listed) | all-mode and digital (IARU Region 1 and 3 plans; APRS in NZ, Taiwan, Japan) |
| APRS | 144.66 | R3 | standard | APRS: Japan | all-mode and digital (IARU Region 1 and 3 plans; APRS in NZ, Taiwan, Japan) |
| APRS | 144.8 | R1 | standard | APRS: Europe, South Africa, Russia | digital communications (IARU Region 1; APRS 144.800) |
| APRS | 144.93 | R2 | standard | APRS: Argentina, Uruguay | digital communications (IARU Region 1; APRS 144.800) |
| APRS | 145.175 | R3 | standard | APRS: Australia | digital and packet in some Region 3 plans (APRS 145.175, Australia) |
| APRS | 145.57 | R2 | standard | APRS: Brazil | FM simplex and digital (local option; APRS 145.570, Brazil) |
| APRS | 145.825 | All | standard | APRS via the ISS and satellites (path ARISS), worldwide | amateur satellites (ISS and satellite APRS 145.825) |
| FT8 | 144.174 | All | standard | FT8 calling (WSJT-X default) | weak-signal SSB/CW and digital (FT8 144.174) |
| WSPR | 144.489 | All | standard | WSPR, tones 144.4904-144.4906 | ARRL 'new OSCAR' segment, used for WSPR 144.489 |
| PUMPKIN | 144.171 | All | proposed | weak-signal digital, just below FT8 | weak-signal SSB/CW and digital (FT8 144.174) |
| PUMPKIN | 144.285 | R2 | proposed | Region 2 beacon segment 144.275-144.300 | propagation beacons (IARU Region 2) |
| PUMPKIN | 144.49 | All | proposed | tones at 144.4915, 800 Hz above the WSPR window | ARRL 'new OSCAR' segment, used for WSPR 144.489 |
| CUCUMBER | 145.05 | All | proposed | packet and digital segment 144.90-145.10 | packet and digital data |
| CUCUMBER | 145.58 | R2 | proposed | FM simplex / digital area; agree locally | FM simplex and digital (local option; APRS 145.570, Brazil) |
| UR | 144.287 | R2 | proposed | Region 2 beacon segment | propagation beacons (IARU Region 2) |
| UR | 144.49 | All | proposed | tones near 144.4915, clear of the WSPR window | ARRL 'new OSCAR' segment, used for WSPR 144.489 |

## 1.25 m (220-225 MHz, ITU Region 2 only; Barbados 222-225)

| Mode | Dial MHz | Region | Status | Notes | Band-plan segment |
|---|---|---|---|---|---|
| APRS | 223.54 | R2 | proposed | digital/packet segment 223.52-223.64; no APRS standard | digital and packet |
| FT8 | 222.065 | R2 | standard | FT8 (WSJT-X default) | weak-signal modes |
| FT8 | 222.08 | R2 | common | FT8 and MSK144 (Pacific Northwest) | weak-signal modes |
| WSPR | 222.0535 | R2 | proposed | no WSPR standard yet; beacon segment 222.050-222.060 | weak-signal modes |
| PUMPKIN | 222.055 | R2 | proposed | beacon segment 222.050-222.060 | weak-signal modes |
| PUMPKIN | 222.13 | R2 | proposed | weak-signal SSB, clear of 222.100 calling | weak-signal modes |
| CUCUMBER | 223.42 | R2 | proposed | FM simplex segment 223.40-223.52 | FM simplex |
| CUCUMBER | 223.58 | R2 | proposed | digital/packet segment 223.52-223.64 | digital and packet |
| UR | 222.13 | R2 | proposed | weak-signal SSB, clear of 222.100 calling | weak-signal modes |

## 70 cm (420-450 MHz; many countries 430-440)

| Mode | Dial MHz | Region | Status | Notes | Band-plan segment |
|---|---|---|---|---|---|
| APRS | 432.5 | R1 | standard | APRS on UHF: Europe (no Region 2 standard) | mixed mode and weak-signal work (FT8 432.174) |
| FT8 | 432.065 | All | standard | FT8 (WSJT-X default) | weak-signal CW/SSB, EME (calling 432.100) |
| FT8 | 432.174 | All | common | FT8, widely used (matches 144.174) | mixed mode and weak-signal work (FT8 432.174) |
| WSPR | 432.3 | R2 | common | WSPR, US groups; beacon segment | mixed mode and weak-signal work (FT8 432.174) |
| WSPR | 432.489 | All | common | WSPR, used in VK; mirrors 144.489 | mixed mode and weak-signal work (FT8 432.174) |
| PUMPKIN | 432.171 | All | proposed | weak-signal digital, just below FT8 | mixed mode and weak-signal work (FT8 432.174) |
| PUMPKIN | 432.31 | R2 | proposed | beacon segment 432.300-432.400, 10 kHz above WSPR | mixed mode and weak-signal work (FT8 432.174) |
| CUCUMBER | 433.5 | R2 | proposed | FM data in 433-435 links/digital; agree locally | auxiliary and repeater links, digital (check local plan) |
| CUCUMBER | 446.1 | R2 | proposed | FM simplex area near 446.000 calling; check local plan | FM simplex and links, local option (446.000 simplex calling) |
| UR | 432.31 | R2 | proposed | beacon segment | mixed mode and weak-signal work (FT8 432.174) |

## Why Pumpkin and Cucumber sit where they do

- **Pumpkin** (under 40 Hz wide, USB) goes in the weak-signal and beacon segments, next to WSPR and FT8 but not on top of them. On 2 m the 144.490 dial puts its tones at 144.4915 MHz, 800 Hz above the WSPR window.
- **Cucumber** is FM, so it needs a 12.5 kHz FM channel: the FM simplex or digital/packet segments, never the weak-signal SSB segment.
- **1.25 m** exists only in ITU Region 2.

Sources: IARU Region 2 band plan (2020), ARRL VHF/UHF band plans, WSJT-X default working frequencies, published WSPR and APRS practice.
