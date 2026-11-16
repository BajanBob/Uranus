# Octopus

**A citizen-science study of 2 m and 70 cm propagation from the eastern Caribbean, using Uranus and
PSK Reporter.** Station 8P5AB, Barbados (GK03gc). Started 16 November 2026.

## Questions

1. **Tropospheric ducting** - How often do 2 m / 70 cm paths open from Barbados over the trade-wind
   inversion and the warm sea (about 28 °C), and how far do they reach (Lesser Antilles, Venezuela,
   Guyana, Cape Verde)? How well do sea temperature, humidity, pressure and the inversion height predict them?
2. **Trans-equatorial propagation (TEP)** - Barbados sits about 26 ° north of the geomagnetic equator;
   Argentina, Uruguay and southern Brazil sit about 20-25 ° south of it. Does 2 m TEP open on those paths
   in the evenings, and how does it follow solar flux and season?
3. **Scatter modes** - aircraft scatter along the Caribbean air routes, meteor scatter during showers.

## Method

- **Listening:** Uranus decodes FT8 / FT4 / WSPR / Pumpkin on 144 and 432 MHz (and HF for context) with the
  IC-9100, uploads every good decode to PSK Reporter, and logs it to `out/spots.jsonl`.
- **Data quality:** suspect decodes (WSJT-X '?' flag, grids in open ocean, Antarctic grids for non-Antarctic
  calls) are logged but excluded from analysis and from PSK Reporter.
- **Daily report:** `python -m uranus octopus` writes `research/octopus/<date>/report.md` and `spots.csv`.
  Add weather and space-weather notes in `<date>/context.md`; they are merged into the report.
- **Context recorded each day:** sea surface temperature, humidity, pressure, upper-air soundings where
  available (inversion height), NOAA Kp / solar flux, and a null result when nothing is heard.

## Days

| Date | Summary |
|---|---|
| [2026-11-16](2026-11-16/report.md) | 20 m FT8 only: 39 stations (3 suspect decodes removed), Europe to Kazakhstan and Madagascar overnight. 2 m / 70 cm: no stations heard (baseline). |

Licence: data CC BY 4.0, code GPL-3.0 (as Uranus).
