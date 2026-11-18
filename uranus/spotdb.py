"""Spot database: out/spots.jsonl loaded into SQLite, with recursive SQL for timelines and band openings.

    python -m uranus spotdb                      # import new lines from out/spots.jsonl into out/spots.db
    python -m uranus spotdb --openings 20m       # band openings over the last 24 h
    python -m uranus spotdb --timeline 2m --slot 120 --hours 6

The JSONL log stays the record Uranus writes to; the database is an index built from it. Imports are
incremental (the byte offset already read is stored), so running it again only adds new spots.

Recursive SQL (WITH RECURSIVE) used here:
* SLOTS   - a series of fixed slots (120 s = one WSPR cycle) across a window, joined to the spots, so
            silent slots are reported as zero instead of disappearing.
* OPENINGS - walks those slots in order, carrying a running "quiet slots" count, and starts a new opening
            when a band comes back after more than ``max_gap`` quiet slots (gaps-and-islands by recursion).
Both have a hard slot limit so a bad window can never run forever.
"""

import json
import os
import sqlite3
import time

from . import propagation

DEFAULT_DB = os.path.join("out", "spots.db")
DEFAULT_JSONL = os.path.join("out", "spots.jsonl")
MAX_SLOTS = 20000

SCHEMA = """
CREATE TABLE IF NOT EXISTS spots (
    id        INTEGER PRIMARY KEY,
    time      REAL NOT NULL,
    call      TEXT NOT NULL,
    grid      TEXT,
    snr       REAL,
    best      REAL,
    freq_hz   REAL,
    band      TEXT,
    mode      TEXT,
    direction TEXT,
    raw       TEXT
);
CREATE INDEX IF NOT EXISTS spots_band_time ON spots (band, time);
CREATE INDEX IF NOT EXISTS spots_call ON spots (call);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

SLOTS_SQL = """
WITH RECURSIVE
slot(k, t0) AS (
    SELECT 0, CAST(:t0 AS REAL)
    UNION ALL
    SELECT k + 1, t0 + :width FROM slot
    WHERE t0 + :width < :t1 AND k + 1 < :max_slots
)
SELECT s.k, s.t0,
       COUNT(sp.id)            AS spots,
       COUNT(DISTINCT sp.call) AS stations,
       MAX(sp.snr)             AS best_snr
FROM slot s
LEFT JOIN spots sp
  ON sp.time >= s.t0 AND sp.time < s.t0 + :width
 AND (:band = '' OR sp.band = :band)
 AND (:direction = '' OR sp.direction = :direction)
GROUP BY s.k, s.t0
ORDER BY s.k
"""

OPENINGS_SQL = """
WITH RECURSIVE
slot(k, t0) AS (
    SELECT 0, CAST(:t0 AS REAL)
    UNION ALL
    SELECT k + 1, t0 + :width FROM slot
    WHERE t0 + :width < :t1 AND k + 1 < :max_slots
),
busy AS (
    SELECT s.k, s.t0, COUNT(sp.id) AS n, MAX(sp.snr) AS best
    FROM slot s
    LEFT JOIN spots sp
      ON sp.time >= s.t0 AND sp.time < s.t0 + :width AND sp.band = :band
     AND (:direction = '' OR sp.direction = :direction)
    GROUP BY s.k, s.t0
),
walk(k, t0, n, best, opening, quiet) AS (
    SELECT k, t0, n, best,
           CASE WHEN n > 0 THEN 1 ELSE 0 END,
           CASE WHEN n > 0 THEN 0 ELSE 1 END
    FROM busy WHERE k = 0
    UNION ALL
    SELECT b.k, b.t0, b.n, b.best,
           CASE WHEN b.n > 0 AND (w.opening = 0 OR w.quiet > :max_gap) THEN w.opening + 1
                ELSE w.opening END,
           CASE WHEN b.n > 0 THEN 0 ELSE w.quiet + 1 END
    FROM walk w JOIN busy b ON b.k = w.k + 1
),
opening AS (
    SELECT opening, MIN(t0) AS start, MAX(t0) + :width AS stop,
           SUM(n) AS spots, COUNT(*) AS busy_slots, MAX(best) AS best_snr
    FROM walk WHERE n > 0 AND opening > 0
    GROUP BY opening
)
SELECT o.opening, o.start, o.stop, o.spots, o.busy_slots, o.best_snr,
       (SELECT COUNT(DISTINCT sp.call) FROM spots sp
         WHERE sp.band = :band AND sp.time >= o.start AND sp.time < o.stop
           AND (:direction = '' OR sp.direction = :direction)) AS stations
FROM opening o
ORDER BY o.opening
"""


def connect(path=DEFAULT_DB):
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    return db


def _row(s):
    try:
        t = float(s.get("time") or 0)
        call = str(s["call"]).strip().upper()
    except (KeyError, TypeError, ValueError):
        return None
    if not call or t <= 0:
        return None
    f = s.get("freq_hz")
    return (t, call, s.get("grid"), s.get("snr"), s.get("best", s.get("snr")), f,
            propagation.band_of(f) if f else s.get("band", "?"), s.get("mode", ""),
            s.get("direction", "rx"), json.dumps(s, separators=(",", ":")))


def add_spots(db, spots):
    rows = [r for r in map(_row, spots) if r]
    db.executemany("INSERT INTO spots (time, call, grid, snr, best, freq_hz, band, mode, direction, raw) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()
    return len(rows)


def import_jsonl(db, path=DEFAULT_JSONL):
    """Add spots written to the JSONL log since the last import. Returns the number added."""
    if not os.path.exists(path):
        return 0
    key = "offset:" + os.path.abspath(path)
    got = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    offset = int(got[0]) if got else 0
    if offset > os.path.getsize(path):  # the log was rotated or replaced: start again
        offset = 0
    spots = []
    with open(path, "rb") as f:
        f.seek(offset)
        for raw in f:
            if not raw.endswith(b"\n"):
                break  # a line still being written; pick it up next time
            offset += len(raw)
            try:
                spots.append(json.loads(raw))
            except ValueError:
                continue
    n = add_spots(db, spots)
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(offset)))
    db.commit()
    return n


def _window(t0, t1, width):
    width = float(width)
    if width <= 0:
        raise ValueError("slot width must be positive")
    if (t1 - t0) / width > MAX_SLOTS:
        raise ValueError(f"more than {MAX_SLOTS} slots: widen the slot or shorten the window")
    return {"t0": float(t0), "t1": float(t1), "width": width, "max_slots": MAX_SLOTS}


def timeline(db, t0, t1, width=120, band="", direction=""):
    """Spots per slot from t0 to t1, quiet slots included."""
    p = _window(t0, t1, width) | {"band": band or "", "direction": direction or ""}
    return [dict(r) for r in db.execute(SLOTS_SQL, p)]


def openings(db, band, t0, t1, width=120, max_gap=2, direction=""):
    """Periods when ``band`` was open: runs of busy slots separated by more than ``max_gap`` quiet slots."""
    p = _window(t0, t1, width) | {"band": band, "max_gap": int(max_gap), "direction": direction or ""}
    return [dict(r) for r in db.execute(OPENINGS_SQL, p)]


def bands(db, t0, t1):
    return [r[0] for r in db.execute(
        "SELECT band FROM spots WHERE time >= ? AND time < ? AND band <> '?' GROUP BY band ORDER BY COUNT(*) DESC",
        (t0, t1))]


def from_spots(spots):
    """An in-memory database holding a list of spot dicts (used by Octopus)."""
    db = connect(":memory:")
    add_spots(db, spots)
    return db


def hhmm(t):
    return time.strftime("%H:%M", time.gmtime(t))


def main(args):
    db = connect(args.db)
    n = import_jsonl(db, args.jsonl)
    total = db.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
    print(f"Imported {n} new spot(s); {total} in {args.db}")
    t1 = time.time()
    t0 = t1 - args.hours * 3600
    t0 -= t0 % args.slot
    if args.openings:
        rows = openings(db, args.openings, t0, t1, args.slot, args.max_gap)
        print(f"{args.openings} openings in the last {args.hours:g} h (UTC):")
        for r in rows or []:
            print(f"  {hhmm(r['start'])}-{hhmm(r['stop'])}  {r['stations']} station(s), {r['spots']} spot(s), "
                  f"best {r['best_snr']:+.0f} dB")
        if not rows:
            print("  none")
    if args.timeline:
        for r in timeline(db, t0, t1, args.slot, args.timeline):
            bar = "#" * min(60, r["spots"])
            print(f"  {hhmm(r['t0'])}  {r['spots']:4d}  {bar}")
