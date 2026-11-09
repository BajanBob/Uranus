"""Station map: who is on, where, how far, and at what SNR.

Writes one self-contained HTML page. Online it draws on OpenStreetMap
(Leaflet); offline it falls back to a built-in Maidenhead-grid map, so the
page always works.

Colours:  blue = online (heard within `online_min` minutes)
          red  = offline (heard earlier)
Lines:    solid = we decoded them, dashed = they decoded us (PSK Reporter),
          thick = both directions (a two-way path)
"""

import html
import json
import time

from . import geo

DEMO_NOTE = "SAMPLE DATA - illustrative stations, not real spots"


def aggregate(spots, home_grid, online_min=30, now=None):
    now = now or time.time()
    home = geo.grid_to_latlon(home_grid)
    by = {}
    for s in spots:
        try:
            lat, lon = geo.grid_to_latlon(s["grid"])
        except (ValueError, KeyError, IndexError):
            continue
        st = by.setdefault(s["call"], {"call": s["call"], "grid": s["grid"], "lat": lat, "lon": lon,
                                        "dirs": set(), "last": 0, "best": -99, "last_snr": None,
                                        "mode": s.get("mode", ""), "freq_hz": s.get("freq_hz", 0), "n": 0})
        st["dirs"].add(s.get("direction", "rx"))
        st["n"] += 1
        snr = s.get("snr")
        if snr is not None and snr == snr:
            st["best"] = max(st["best"], snr)
        if s["time"] >= st["last"]:
            st.update(last=s["time"], last_snr=snr, mode=s.get("mode", st["mode"]),
                      freq_hz=s.get("freq_hz", st["freq_hz"]), grid=s["grid"], lat=lat, lon=lon)
    out = []
    for st in by.values():
        st["km"] = round(geo.distance_km(home, (st["lat"], st["lon"])))
        st["brg"] = round(geo.bearing_deg(home, (st["lat"], st["lon"])))
        st["online"] = (now - st["last"]) <= online_min * 60
        st["ago_min"] = round((now - st["last"]) / 60)
        st["dirs"] = sorted(st["dirs"])
        out.append(st)
    out.sort(key=lambda s: (not s["online"], -s["last"]))
    return out


def demo_spots(now=None):
    """Clearly labelled sample stations around Barbados for previews."""
    now = now or time.time()
    places = [("SAMPLE1", 13.9, -61.0, -14, 4, "rx"), ("SAMPLE2", 14.6, -61.0, -22, 9, "heard"),
              ("SAMPLE3", 10.65, -61.5, -27, 2, "rx"), ("SAMPLE3", 10.65, -61.5, -25, 3, "heard"),
              ("SAMPLE4", 12.1, -61.7, -19, 18, "rx"), ("SAMPLE5", 16.2, -61.6, -29, 52, "heard"),
              ("SAMPLE6", 10.5, -66.9, -31, 95, "rx"), ("SAMPLE7", 18.4, -66.1, -30, 140, "heard"),
              ("SAMPLE8", 15.3, -61.4, -17, 7, "rx"), ("SAMPLE8", 15.3, -61.4, -20, 8, "heard")]
    out = []
    for call, lat, lon, snr, ago, d in places:
        out.append({"time": int(now - ago * 60), "call": call, "grid": geo.latlon_to_grid(lat, lon),
                    "snr": snr, "freq_hz": 144491500, "mode": "URC", "direction": d})
    return out


def render(stations, home_call, home_grid, title="Uranus station map", note="", online_min=30):
    hl = geo.grid_to_latlon(home_grid)
    data = json.dumps({"home": {"call": home_call, "grid": home_grid, "lat": hl[0], "lon": hl[1]},
                       "stations": stations, "online_min": online_min,
                       "generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())})
    return TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__NOTE__", html.escape(note)) \
                   .replace("__DATA__", data.replace("</", "<\\/"))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
/* Layout: status strip, then map (left) and station log (right); stacks on phones. */
:root {
  --bg: #f3f1eb; --ink: #17212b; --muted: #5d6872; --rule: #d3cec2; --panel: #ffffff;
  --online: #1d63d6; --offline: #c8372d; --home: #c7791a; --sea: #e3ebef; --grid: #b9c6cf;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  --body: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#0f151b; --ink:#e5e1d6; --muted:#97a1aa; --rule:#2b3540; --panel:#151d26;
    --online:#5b9bff; --offline:#ff6b5e; --home:#e5a24a; --sea:#132331; --grid:#2c4558; color-scheme: dark; }
}
:root[data-theme="dark"] { --bg:#0f151b; --ink:#e5e1d6; --muted:#97a1aa; --rule:#2b3540; --panel:#151d26;
  --online:#5b9bff; --offline:#ff6b5e; --home:#e5a24a; --sea:#132331; --grid:#2c4558; color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body { background: var(--bg); color: var(--ink); font: 15px/1.45 var(--body); display: flex; flex-direction: column; }
header { display: flex; flex-wrap: wrap; gap: 10px 26px; align-items: baseline; padding: 12px 16px; border-bottom: 2px solid var(--ink); }
header h1 { margin: 0; font-size: 1.15rem; letter-spacing: .06em; text-transform: uppercase; }
.stat { font: 600 .82rem var(--mono); color: var(--muted); }
.stat b { color: var(--ink); font-size: 1.05rem; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: 0; }
.note { width: 100%; font: 600 .78rem var(--mono); color: var(--offline); letter-spacing: .05em; }
.note:empty { display: none; }
main { flex: 1; display: grid; grid-template-columns: minmax(0, 1fr) minmax(420px, 36%); min-height: 0; }
#map, #fallback { width: 100%; height: 100%; min-height: 420px; background: var(--sea); }
#fallback { display: none; }
#fallback text { font-family: var(--mono); }
aside { border-left: 1px solid var(--rule); background: var(--panel); overflow: auto; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 10px 14px; border-bottom: 1px solid var(--rule); font: .78rem var(--mono); color: var(--muted); }
.legend svg { vertical-align: middle; margin-right: 4px; }
table { width: 100%; border-collapse: collapse; font-size: .86rem; }
th, td { padding: 7px 6px; border-bottom: 1px solid var(--rule); text-align: left; white-space: nowrap; }
th { font: 600 .7rem var(--mono); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); position: sticky; top: 0; background: var(--panel); }
td.n { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
td.call { font: 600 .88rem var(--mono); }
tr.off td { color: var(--muted); }
tr:hover td { background: color-mix(in srgb, var(--online) 7%, transparent); cursor: pointer; }
.dir { font: .72rem var(--mono); color: var(--muted); }
footer { padding: 6px 16px; font: .72rem var(--mono); color: var(--muted); border-top: 1px solid var(--rule); }
@media (max-width: 860px) { main { grid-template-columns: minmax(0, 1fr); } aside { border-left: 0; border-top: 1px solid var(--rule); } #map, #fallback { min-height: 360px; } }
</style>
</head>
<body>
<header>
  <h1>Uranus · station map</h1>
  <span class="stat" id="home"></span>
  <span class="stat"><span class="dot" style="background:var(--online)"></span>online <b id="non">0</b></span>
  <span class="stat"><span class="dot" style="background:var(--offline)"></span>offline <b id="noff">0</b></span>
  <span class="stat">furthest <b id="far">-</b></span>
  <span class="stat">best SNR <b id="best">-</b></span>
  <div class="note">__NOTE__</div>
</header>
<main>
  <div><div id="map"></div><svg id="fallback" role="img" aria-label="Map of stations on a Maidenhead grid"></svg></div>
  <aside>
    <div class="legend">
      <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="2"/></svg>we heard them</span>
      <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3"/></svg>they heard us</span>
      <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="4"/></svg>both ways</span>
    </div>
    <table>
      <thead><tr><th>Station</th><th>Grid</th><th style="text-align:right">km</th><th style="text-align:right">Brg</th><th style="text-align:right">SNR</th><th style="text-align:right">Best</th><th style="text-align:right">Heard</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
  </aside>
</main>
<footer id="foot"></footer>
<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("data").textContent);
  var S = D.stations, H = D.home;
  var css = getComputedStyle(document.documentElement);
  function col(n) { return css.getPropertyValue(n).trim(); }
  function fmtSnr(v) { return (v === null || v === undefined || v !== v || v <= -99) ? "-" : (v > 0 ? "+" : "") + Math.round(v); }
  function ago(m) { return m < 1 ? "now" : m < 60 ? m + " min" : Math.round(m / 60) + " h"; }
  function dirTxt(d) { return d.length > 1 ? "both ways" : d[0] === "rx" ? "we heard" : "heard us"; }

  document.getElementById("home").innerHTML = "<b>" + H.call + "</b> " + H.grid;
  var on = S.filter(function (s) { return s.online; });
  document.getElementById("non").textContent = on.length;
  document.getElementById("noff").textContent = S.length - on.length;
  if (S.length) {
    var far = S.reduce(function (a, b) { return b.km > a.km ? b : a; });
    document.getElementById("far").textContent = far.km.toLocaleString() + " km (" + far.call + ")";
    var best = S.reduce(function (a, b) { return b.best > a.best ? b : a; });
    document.getElementById("best").textContent = fmtSnr(best.best) + " dB (" + best.call + ")";
  }
  document.getElementById("foot").textContent = "Generated " + D.generated + " · online = heard in the last " + D.online_min +
    " min · SNR in 2500 Hz · distances great-circle from " + H.grid;

  var rows = document.getElementById("rows"), focus = function () {};
  S.forEach(function (s, i) {
    var tr = document.createElement("tr");
    if (!s.online) tr.className = "off";
    tr.innerHTML = '<td class="call"><span class="dot" style="background:' + (s.online ? "var(--online)" : "var(--offline)") + '"></span>' +
      s.call + '<div class="dir">' + dirTxt(s.dirs) + " · " + s.mode + "</div></td><td>" + s.grid + '</td><td class="n">' +
      s.km.toLocaleString() + '</td><td class="n">' + s.brg + '°</td><td class="n">' + fmtSnr(s.last_snr) + '</td><td class="n">' +
      fmtSnr(s.best) + '</td><td class="n">' + ago(s.ago_min) + "</td>";
    tr.addEventListener("click", function () { focus(i); });
    rows.appendChild(tr);
  });
  if (!S.length) rows.innerHTML = '<tr><td colspan="7">No stations yet. Run <b>Listen</b> or fetch PSK Reporter spots.</td></tr>';

  function popup(s) {
    return "<b>" + s.call + "</b> · " + s.grid + "<br>" + s.km.toLocaleString() + " km at " + s.brg + "°<br>SNR " +
      fmtSnr(s.last_snr) + " dB (best " + fmtSnr(s.best) + ")<br>" + dirTxt(s.dirs) + " · " + s.mode + " · " + ago(s.ago_min) + " ago";
  }

  // ---------- online: Leaflet on OpenStreetMap ----------
  if (window.L) {
    var map = L.map("map", { worldCopyJump: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    var pts = [[H.lat, H.lon]], markers = [];
    L.circleMarker([H.lat, H.lon], { radius: 9, color: "#fff", weight: 2, fillColor: col("--home"), fillOpacity: 1 })
      .addTo(map).bindTooltip(H.call + " (home)", { permanent: true, direction: "right" });
    S.forEach(function (s) {
      var c = s.online ? col("--online") : col("--offline");
      L.polyline([[H.lat, H.lon], [s.lat, s.lon]], { color: c, weight: s.dirs.length > 1 ? 4 : 2, opacity: .75,
        dashArray: s.dirs.length === 1 && s.dirs[0] === "heard" ? "6 5" : null }).addTo(map);
      var m = L.circleMarker([s.lat, s.lon], { radius: 7, color: "#fff", weight: 2, fillColor: c, fillOpacity: 1 })
        .addTo(map).bindPopup(popup(s)).bindTooltip(s.call, { permanent: true, direction: "right", className: "lbl" });
      markers.push(m); pts.push([s.lat, s.lon]);
    });
    map.fitBounds(pts, { padding: [40, 40], maxZoom: 9 });
    focus = function (i) { markers[i].openPopup(); map.panTo(markers[i].getLatLng()); };
    return;
  }

  // ---------- offline: built-in Maidenhead-grid map ----------
  document.getElementById("map").style.display = "none";
  var svg = document.getElementById("fallback");
  svg.style.display = "block";
  var NS = "http://www.w3.org/2000/svg";
  function el(n, a, t) { var e = document.createElementNS(NS, n); for (var k in a) e.setAttribute(k, a[k]); if (t !== undefined) e.textContent = t; svg.appendChild(e); return e; }
  function draw() {
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var r = svg.getBoundingClientRect(), W = r.width, Hh = r.height;
    svg.setAttribute("viewBox", "0 0 " + W + " " + Hh);
    var lats = [H.lat].concat(S.map(function (s) { return s.lat; })), lons = [H.lon].concat(S.map(function (s) { return s.lon; }));
    var la0 = Math.min.apply(0, lats) - 1, la1 = Math.max.apply(0, lats) + 1, lo0 = Math.min.apply(0, lons) - 1.5, lo1 = Math.max.apply(0, lons) + 1.5;
    var k = Math.cos((la0 + la1) / 2 * Math.PI / 180), pad = 30;
    var sx = (W - 2 * pad) / ((lo1 - lo0) * k), sy = (Hh - 2 * pad) / (la1 - la0), sc = Math.min(sx, sy);
    var cx = (lo0 + lo1) / 2, cy = (la0 + la1) / 2;
    function P(lat, lon) { return [W / 2 + (lon - cx) * k * sc, Hh / 2 - (lat - cy) * sc]; }
    // Maidenhead squares (2 deg x 1 deg) with labels
    var g0 = Math.floor((cx - (W / 2) / (k * sc) + 180) / 2) * 2 - 180, g1 = cx + (W / 2) / (k * sc);
    for (var lo = g0; lo <= g1; lo += 2) { var a = P(0, lo); el("line", { x1: a[0], y1: 0, x2: a[0], y2: Hh, stroke: col("--grid"), "stroke-width": lo % 20 === 0 ? 2 : 1 }); }
    var h0 = Math.floor(cy - (Hh / 2) / sc), h1 = cy + (Hh / 2) / sc;
    for (var la = h0; la <= h1; la += 1) { var b = P(la, 0); el("line", { x1: 0, y1: b[1], x2: W, y2: b[1], stroke: col("--grid"), "stroke-width": (la + 90) % 10 === 0 ? 2 : 1 }); }
    for (lo = g0; lo <= g1; lo += 2) for (la = h0; la <= h1; la += 1) {
      var p = P(la + 0.5, lo + 1), F = String.fromCharCode(65 + Math.floor((lo + 180) / 20)) + String.fromCharCode(65 + Math.floor((la + 90) / 10));
      var sq = F + Math.floor(((lo + 180) % 20) / 2) + Math.floor((la + 90) % 10);
      if (sc > 40) el("text", { x: p[0], y: p[1] + 4, "text-anchor": "middle", "font-size": 11, fill: col("--grid") }, sq);
    }
    var h = P(H.lat, H.lon);
    S.slice().reverse().forEach(function (s) {
      var q = P(s.lat, s.lon), c = s.online ? col("--online") : col("--offline");
      el("line", { x1: h[0], y1: h[1], x2: q[0], y2: q[1], stroke: c, "stroke-width": s.dirs.length > 1 ? 4 : 2, opacity: .8,
        "stroke-dasharray": s.dirs.length === 1 && s.dirs[0] === "heard" ? "7 5" : "none" });
    });
    S.forEach(function (s) {
      var q = P(s.lat, s.lon), c = s.online ? col("--online") : col("--offline");
      var g = el("circle", { cx: q[0], cy: q[1], r: 7, fill: c, stroke: col("--panel"), "stroke-width": 2 });
      var t = document.createElementNS(NS, "title"); t.textContent = popup(s).replace(/<br>/g, "\n").replace(/<[^>]+>/g, ""); g.appendChild(t);
      el("text", { x: q[0] + 11, y: q[1] - 2, "font-size": 12, "font-weight": 600, fill: col("--ink") }, s.call);
      el("text", { x: q[0] + 11, y: q[1] + 12, "font-size": 11, fill: col("--muted") }, s.km + " km · " + fmtSnr(s.last_snr) + " dB");
    });
    el("circle", { cx: h[0], cy: h[1], r: 9, fill: col("--home"), stroke: col("--panel"), "stroke-width": 2 });
    el("text", { x: h[0] + 13, y: h[1] + 4, "font-size": 13, "font-weight": 700, fill: col("--ink") }, H.call + " (home)");
    el("text", { x: 10, y: Hh - 10, "font-size": 11, fill: col("--muted") }, "Offline view: Maidenhead grid squares. Connect to the internet for the OpenStreetMap view.");
  }
  draw();
  window.addEventListener("resize", draw);
})();
</script>
</body>
</html>
"""
