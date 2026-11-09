"""Spot log: one JSON object per line in out/spots.jsonl.

direction "rx"    = we decoded them
direction "heard" = they decoded us (from PSK Reporter)
"""

import json
import os
import time

DEFAULT_PATH = os.path.join("out", "spots.jsonl")


def add(spot, path=DEFAULT_PATH):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    spot = {"time": int(time.time()), **spot}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(spot) + "\n")
    return spot


def load(path=DEFAULT_PATH, since_s=None):
    if not os.path.exists(path):
        return []
    cutoff = time.time() - since_s if since_s else 0
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                s = json.loads(line)
            except ValueError:
                continue
            if s.get("time", 0) >= cutoff:
                out.append(s)
    return out
