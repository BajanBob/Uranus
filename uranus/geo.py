"""Maidenhead locators, great-circle distance and bearing."""

import math


def grid_to_latlon(grid):
    """Centre of a 4- or 6-character Maidenhead square (lat, lon)."""
    g = grid.strip().upper()
    if len(g) < 4:
        raise ValueError("grid needs at least 4 characters")
    lon = (ord(g[0]) - 65) * 20 - 180 + int(g[2]) * 2
    lat = (ord(g[1]) - 65) * 10 - 90 + int(g[3])
    if len(g) >= 6:
        lon += (ord(g[4]) - 65) * (2 / 24) + 1 / 24
        lat += (ord(g[5]) - 65) * (1 / 24) + 1 / 48
    else:
        lon += 1.0
        lat += 0.5
    return lat, lon


def latlon_to_grid(lat, lon, chars=6):
    lon += 180
    lat += 90
    g = chr(65 + int(lon // 20)) + chr(65 + int(lat // 10))
    g += str(int((lon % 20) // 2)) + str(int(lat % 10))
    if chars >= 6:
        g += chr(97 + int((lon % 2) * 12)) + chr(97 + int((lat % 1) * 24))
    return g


def distance_km(a, b):
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def bearing_deg(a, b):
    (la1, lo1), (la2, lo2) = [(math.radians(x), math.radians(y)) for x, y in (a, b)]
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360
