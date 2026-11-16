"""Plausibility checks for decoded stations, so false decodes stay off the map and PSK Reporter.

FT8/FT4 decoders occasionally produce false decodes near the threshold (around -20 to -24 dB), above all
with a-priori (AP) decoding. WSJT-X marks the doubtful ones with '?'. On top of that flag, a decode is
suspect when its grid square lies in open ocean far from any land (and the call is not /MM), or in
Antarctica while the call is not an Antarctic one. Suspect decodes are still shown in the console.
"""

import json
import math

from . import geo

ANTARCTIC = ("KC4", "VP8", "RI1", "DP0", "DP1", "8J1", "VK0", "ZL5", "CE9", "FT0", "FT2", "FT4", "FT5", "FT8",
             "OR4", "ZS7", "3Y", "VU3", "HL8", "EM1", "LU1Z", "LU2Z", "LU4Z", "LU5Z", "LU6Z", "LU7Z")
OCEAN_KM = 250.0
_LAND = None


def _land():
    """Land polygons (outer rings) with bounding boxes, from the built-in world map."""
    global _LAND
    if _LAND is None:
        from .worldmap import WORLD
        polys = json.loads(WORLD)["coordinates"]
        _LAND = []
        for p in polys:
            ring = p[0]
            xs, ys = [c[0] for c in ring], [c[1] for c in ring]
            _LAND.append((min(xs), max(xs), min(ys), max(ys), ring))
    return _LAND


def _inside(lon, lat, ring):
    n, c = len(ring), False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[i - 1]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-12) + x1:
            c = not c
    return c


def km_to_land(lat, lon):
    """0 on land, else approximate distance (km) to the nearest coastline point."""
    best = 1e9
    for x0, x1, y0, y1, ring in _land():
        if x0 <= lon <= x1 and y0 <= lat <= y1 and _inside(lon, lat, ring):
            return 0.0
        # cheap reject: bounding box far away
        dx = max(x0 - lon, 0, lon - x1) * 111 * math.cos(math.radians(lat))
        dy = max(y0 - lat, 0, lat - y1) * 111
        if math.hypot(dx, dy) > best:
            continue
        for x, y in ring[::2]:
            d = geo.distance_km((lat, lon), (y, x))
            if d < best:
                best = d
    return best


def suspect(call, grid, flags=""):
    """Reason string if this decode looks false, else ''."""
    if "?" in (flags or ""):
        return "low-confidence decode (WSJT-X '?')"
    if not call or not grid:
        return ""
    c = call.upper()
    if c.endswith("/MM") or c.endswith("/AM"):
        return ""
    try:
        lat, lon = geo.grid_to_latlon(grid[:4])
    except (ValueError, IndexError):
        return "unreadable grid"
    if lat < -60 and not c.startswith(ANTARCTIC):
        return f"grid {grid} is in Antarctica but {call} is not an Antarctic station"
    d = km_to_land(lat, lon)
    if d > OCEAN_KM:
        return f"grid {grid} is open ocean, {d:.0f} km from land, and {call} is not /MM"
    return ""
