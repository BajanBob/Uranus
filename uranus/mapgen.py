"""Station map: who is on, on which band, where, how far, at what SNR,
and by which propagation mode.

Writes one self-contained HTML page. Online it draws on OpenStreetMap
(Leaflet); offline it falls back to a built-in Maidenhead-grid map.

Marker fill and line colour = band (2 m teal, 70 cm violet).
Marker ring = status: blue = online (heard within `online_min` minutes),
red = offline. Offline stations are drawn faded.
Lines: solid = we decoded them, dashed = they decoded us (PSK Reporter),
thick = both directions.
"""

import html
import json
import time

from . import geo, propagation

DEMO_NOTE = "SAMPLE DATA - illustrative stations, not real spots"
F2M, F70 = 144_491_500, 432_301_500


def aggregate(spots, home_grid, online_min=30, now=None, home_latlon=None, ant_heights=(10.0, 10.0)):
    now = now or time.time()
    home = home_latlon or geo.grid_to_latlon(home_grid)
    by = {}
    for s in spots:
        try:
            lat, lon = geo.grid_to_latlon(s["grid"])
        except (ValueError, KeyError, IndexError):
            continue
        band = propagation.band_of(s.get("freq_hz"))
        st = by.setdefault((s["call"], band), {
            "call": s["call"], "band": band, "grid": s["grid"], "lat": lat, "lon": lon, "dirs": set(),
            "last": 0, "best": -99, "last_snr": None, "mode": s.get("mode", ""), "freq_hz": s.get("freq_hz", 0),
            "n": 0, "times": [], "fades": [], "spreads": []})
        st["dirs"].add(s.get("direction", "rx"))
        st["n"] += 1
        st["times"].append(s["time"])
        if s.get("fade_db") is not None:
            st["fades"].append(s["fade_db"])
            st["spreads"].append(s.get("spread_hz", 0.0))
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
        recent = [t for t in st.pop("times") if st["last"] - t <= 3600]
        steady = min(1.0, len(set(int(t) // 60 for t in recent)) / 4.0)
        fades, spreads = st.pop("fades"), st.pop("spreads")
        fade = sum(fades) / len(fades) if fades else None
        spread = sum(spreads) / len(spreads) if spreads else None
        res = propagation.classify(home, (st["lat"], st["lon"]), st["band"], st["last"],
                                   snr=st["last_snr"], fade_db=fade, spread_hz=spread, steady=steady,
                                   ant_heights=ant_heights)
        st["prop"] = {k: round(p, 3) for k, p, _ in res}
        st["likely"] = res[0][0]
        st["likely_name"] = propagation.MODES[res[0][0]]
        st["likely_p"] = round(res[0][1] * 100)
        st["why"] = res[0][2][:3]
        st["second"] = f"{propagation.MODES[res[1][0]]} {round(res[1][1] * 100)}%"
        out.append(st)
    out.sort(key=lambda s: (not s["online"], -s["last"]))
    return out


def demo_spots(now=None):
    """Clearly labelled sample stations around Barbados on 2 m and 70 cm."""
    now = now or time.time()
    # call, lat, lon, band freq, snr, minutes ago (list = repeated decodes), direction, fade dB, spread Hz
    places = [
        ("SAMPLE1", 13.9, -61.0, F2M, -14, [4, 9, 14, 19], "rx", 0.6, 0.02),
        ("SAMPLE2", 14.6, -61.0, F70, -22, [9], "heard", None, None),
        ("SAMPLE3", 10.65, -61.5, F70, -27, [2, 7, 12], "rx", 1.0, 0.03),
        ("SAMPLE3", 10.65, -61.5, F70, -25, [3], "heard", None, None),
        ("SAMPLE4", 12.1, -61.7, F2M, -19, [18], "rx", 4.6, 0.30),
        ("SAMPLE5", 16.2, -61.6, F2M, -29, [52], "heard", None, None),
        ("SAMPLE6", 10.5, -66.9, F70, -12, [95, 100, 105, 110, 115], "rx", 0.7, 0.02),
        ("SAMPLE7", 18.5, -69.9, F2M, -24, [140], "rx", 6.5, 0.45),
        ("SAMPLE8", 15.3, -61.4, F2M, -17, [7, 12], "rx", 0.8, 0.02),
        ("SAMPLE8", 15.3, -61.4, F70, -20, [8], "heard", None, None),
        ("SAMPLE9", 25.0, -77.4, F2M, -8, [25, 30], "rx", 2.5, 0.12),
        ("SAMPLE10", -23.5, -46.6, F2M, -15, [6], "rx", 7.5, 0.9),
    ]
    out = []
    for call, lat, lon, f, snr, agos, d, fade, spread in places:
        for i, ago in enumerate(agos):
            sp = {"time": int(now - ago * 60), "call": call, "grid": geo.latlon_to_grid(lat, lon),
                  "snr": snr - (i % 2), "freq_hz": f, "mode": "URC", "direction": d}
            if fade is not None:
                sp.update(fade_db=fade, spread_hz=spread)
            out.append(sp)
    return out


def render(stations, home_call, home_grid, title="Uranus station map", note="", online_min=30):
    hl = geo.grid_to_latlon(home_grid)
    summary = propagation.band_summary([s for s in stations if s["online"]] or stations)
    data = json.dumps({"home": {"call": home_call, "grid": home_grid, "lat": hl[0], "lon": hl[1]},
                       "stations": stations, "online_min": online_min, "summary": summary,
                       "modes": propagation.MODES,
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
/* Layout: status strip; map; then per-band propagation cards and the station log. */
:root {
  --bg: #f3f1eb; --ink: #17212b; --muted: #5d6872; --rule: #d3cec2; --panel: #ffffff;
  --b2m: #0b8a6c; --b70: #8a3fd0; --online: #1d63d6; --offline: #c8372d; --home: #c7791a;
  --sea: #e3ebef; --grid: #b9c6cf;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  --body: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#0f151b; --ink:#e5e1d6; --muted:#97a1aa; --rule:#2b3540; --panel:#151d26;
    --b2m:#2fc79f; --b70:#b98cff; --online:#5b9bff; --offline:#ff6b5e; --home:#e5a24a; --sea:#132331; --grid:#2c4558; color-scheme: dark; }
}
:root[data-theme="dark"] { --bg:#0f151b; --ink:#e5e1d6; --muted:#97a1aa; --rule:#2b3540; --panel:#151d26;
  --b2m:#2fc79f; --b70:#b98cff; --online:#5b9bff; --offline:#ff6b5e; --home:#e5a24a; --sea:#132331; --grid:#2c4558; color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--ink); font: 15px/1.45 var(--body); }
header { display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; padding: 12px 16px; border-bottom: 2px solid var(--ink); }
header h1 { margin: 0; font-size: 1.1rem; letter-spacing: .06em; text-transform: uppercase; }
.stat { font: 600 .8rem var(--mono); color: var(--muted); }
.stat b { color: var(--ink); font-size: 1rem; }
.sw { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }
.ring { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; border: 3px solid; background: var(--panel); }
.note { width: 100%; font: 600 .78rem var(--mono); color: var(--offline); letter-spacing: .05em; }
.note:empty { display: none; }
#mapwrap { height: 58vh; min-height: 380px; border-bottom: 1px solid var(--rule); }
#map, #fallback { width: 100%; height: 100%; background: var(--sea); }
#fallback { display: none; }
#fallback text { font-family: var(--mono); }
.lbl { font: 600 11px/1.25 var(--mono); background: rgba(255,255,255,.88); border: 0; box-shadow: none; padding: 2px 5px; color: #17212b; }
.lbl::before { display: none; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; padding: 10px 16px; border-bottom: 1px solid var(--rule); font: .78rem var(--mono); color: var(--muted); }
.legend svg { vertical-align: middle; margin-right: 4px; }
.bands { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 0; border-bottom: 1px solid var(--rule); }
.band { padding: 14px 16px; border-right: 1px solid var(--rule); }
.band h2 { margin: 0 0 4px; font-size: 1rem; letter-spacing: .04em; display: flex; gap: 8px; align-items: center; }
.band .meta { font: .78rem var(--mono); color: var(--muted); margin-bottom: 8px; }
.band .top { font-weight: 600; margin-bottom: 8px; }
.bar { display: grid; grid-template-columns: 11.5rem minmax(0, 1fr) 3rem; gap: 8px; align-items: center; font-size: .82rem; margin: 3px 0; }
.bar i { display: block; height: 9px; border-radius: 2px; }
.bar span:last-child { font: .78rem var(--mono); text-align: right; color: var(--muted); }
.tbl { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .86rem; min-width: 880px; }
th, td { padding: 7px 8px; border-bottom: 1px solid var(--rule); text-align: left; white-space: nowrap; vertical-align: top; }
th { font: 600 .7rem var(--mono); text-transform: uppercase; letter-spacing: .07em; color: var(--muted); background: var(--panel); }
td.n { font-family: var(--mono); font-variant-numeric: tabular-nums; text-align: right; }
td.call { font: 600 .88rem var(--mono); }
td.prop { white-space: normal; min-width: 260px; }
td.prop small { display: block; color: var(--muted); font-size: .76rem; }
.chip { display: inline-block; font: 600 .72rem var(--mono); color: #fff; border-radius: 3px; padding: 1px 6px; }
tr.off td { opacity: .62; }
tr:hover td { background: color-mix(in srgb, var(--online) 6%, transparent); cursor: pointer; }
.dir { font: .72rem var(--mono); color: var(--muted); }
footer { padding: 8px 16px 18px; font: .72rem var(--mono); color: var(--muted); }
</style>
</head>
<body>
<header>
  <h1>Uranus · station map</h1>
  <span class="stat" id="home"></span>
  <span class="stat"><span class="sw" style="background:var(--b2m)"></span>2 m <b id="n2m">0</b></span>
  <span class="stat"><span class="sw" style="background:var(--b70)"></span>70 cm <b id="n70">0</b></span>
  <span class="stat"><span class="ring" style="border-color:var(--online)"></span>online <b id="non">0</b></span>
  <span class="stat"><span class="ring" style="border-color:var(--offline)"></span>offline <b id="noff">0</b></span>
  <div class="note">__NOTE__</div>
</header>
<div id="mapwrap"><div id="map"></div><svg id="fallback" role="img" aria-label="Map of stations on a Maidenhead grid"></svg></div>
<div class="legend">
  <span><span class="sw" style="background:var(--b2m)"></span>2 m station</span>
  <span><span class="sw" style="background:var(--b70)"></span>70 cm station</span>
  <span><span class="ring" style="border-color:var(--online)"></span>online (ring)</span>
  <span><span class="ring" style="border-color:var(--offline)"></span>offline (ring, faded)</span>
  <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="2"/></svg>we heard them</span>
  <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="2" stroke-dasharray="4 3"/></svg>they heard us</span>
  <span><svg width="26" height="8"><line x1="0" y1="4" x2="26" y2="4" stroke="currentColor" stroke-width="4"/></svg>both ways</span>
</div>
<section class="bands" id="bands" aria-label="Propagation by band"></section>
<div class="tbl">
  <table>
    <thead><tr><th>Station</th><th>Band</th><th>Grid</th><th style="text-align:right">km</th><th style="text-align:right">Brg</th>
      <th style="text-align:right">SNR</th><th style="text-align:right">Best</th><th style="text-align:right">Heard</th><th>Likely propagation</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</div>
<footer id="foot"></footer>
<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
(function () {
  var D = JSON.parse(document.getElementById("data").textContent);
  var S = D.stations, H = D.home, M = D.modes;
  var css = getComputedStyle(document.documentElement);
  function col(n) { return css.getPropertyValue(n).trim(); }
  function bandCol(b) { return b === "70cm" ? col("--b70") : col("--b2m"); }
  function bandTxt(b) { return b === "70cm" ? "70 cm" : b === "2m" ? "2 m" : "?"; }
  function stCol(s) { return s.online ? col("--online") : col("--offline"); }
  function fmtSnr(v) { return (v === null || v === undefined || v !== v || v <= -99) ? "-" : (v > 0 ? "+" : "") + Math.round(v); }
  function ago(m) { return m < 1 ? "now" : m < 60 ? m + " min" : Math.round(m / 60) + " h"; }
  function dirTxt(d) { return d.length > 1 ? "both ways" : d[0] === "rx" ? "we heard" : "heard us"; }
  function overlaps(a, b) { return !(a.right < b.left || a.left > b.right || a.bottom < b.top || a.top > b.bottom); }
  function declutter(items, force) {
    // items: [{el, prio}] - keep higher-priority labels, hide any that collide with a kept one
    var kept = [];
    items.slice().sort(function (a, b) { return (b.idx === force) - (a.idx === force) || b.prio - a.prio; }).forEach(function (it) {
      it.el.style.visibility = "visible";
      var r = it.el.getBoundingClientRect(), pad = { left: r.left - 3, right: r.right + 3, top: r.top - 2, bottom: r.bottom + 2 };
      if (kept.some(function (k) { return overlaps(k, pad); })) it.el.style.visibility = "hidden"; else kept.push(pad);
    });
  }
  function prio(s) { return (s.online ? 1000 : 0) + Math.min(s.km, 999); }
  function esc(t) { return String(t).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  document.getElementById("home").innerHTML = "<b>" + esc(H.call) + "</b> " + esc(H.grid);
  var on = S.filter(function (s) { return s.online; });
  document.getElementById("non").textContent = on.length;
  document.getElementById("noff").textContent = S.length - on.length;
  document.getElementById("n2m").textContent = S.filter(function (s) { return s.band === "2m"; }).length;
  document.getElementById("n70").textContent = S.filter(function (s) { return s.band === "70cm"; }).length;
  document.getElementById("foot").textContent = "Generated " + D.generated + " · online = heard in the last " + D.online_min +
    " min · SNR in 2500 Hz · great-circle distance and bearing from " + H.grid +
    " · propagation is an evidence-weighted estimate (distance, band, time, season, path, measured fading), not a certainty";

  // per-band propagation cards
  var palette = { los: "#7a8794", tropo_scatter: "#2f80c9", ducting: "#0b8a6c", aircraft: "#d08a1c", meteor: "#c8372d", es: "#8a3fd0", tep: "#b0337f" };
  var bands = document.getElementById("bands");
  ["2m", "70cm"].forEach(function (b) {
    var r = D.summary[b];
    var div = document.createElement("div"); div.className = "band";
    var h = '<h2><span class="sw" style="background:' + bandCol(b) + '"></span>' + bandTxt(b) + " propagation now</h2>";
    if (!r) { div.innerHTML = h + '<div class="meta">No stations heard on this band yet.</div>'; bands.appendChild(div); return; }
    var items = Object.keys(r.probs).map(function (k) { return [k, r.probs[k]]; }).sort(function (a, c) { return c[1] - a[1]; }).slice(0, 4);
    h += '<div class="meta">' + r.n + " station" + (r.n === 1 ? "" : "s") + " · furthest " + r.max_km.toLocaleString() + " km</div>";
    h += '<div class="top">Most likely: ' + esc(M[r.top]) + " (" + Math.round(r.probs[r.top] * 100) + "%)</div>";
    items.forEach(function (it) {
      h += '<div class="bar"><span>' + esc(M[it[0]]) + '</span><i style="width:' + Math.max(2, it[1] * 100) + "%;background:" + palette[it[0]] + '"></i><span>' + Math.round(it[1] * 100) + "%</span></div>";
    });
    div.innerHTML = h; bands.appendChild(div);
  });

  // station table
  var rows = document.getElementById("rows"), focus = function () {};
  S.forEach(function (s, i) {
    var tr = document.createElement("tr");
    if (!s.online) tr.className = "off";
    tr.innerHTML = '<td class="call"><span class="ring" style="border-color:' + stCol(s) + ";background:" + bandCol(s.band) + '"></span>' +
      esc(s.call) + '<div class="dir">' + dirTxt(s.dirs) + " · " + esc(s.mode) + '</div></td><td><span class="chip" style="background:' + bandCol(s.band) + '">' + bandTxt(s.band) +
      "</span></td><td>" + esc(s.grid) + '</td><td class="n">' + s.km.toLocaleString() + '</td><td class="n">' + s.brg + '°</td><td class="n">' +
      fmtSnr(s.last_snr) + '</td><td class="n">' + fmtSnr(s.best) + '</td><td class="n">' + ago(s.ago_min) + '</td><td class="prop"><b>' +
      esc(s.likely_name) + "</b> " + s.likely_p + "%<small>" + esc((s.why || []).join("; ") || "distance and band") + " · next: " + esc(s.second) + "</small></td>";
    tr.addEventListener("click", function () { focus(i); });
    rows.appendChild(tr);
  });
  if (!S.length) rows.innerHTML = '<tr><td colspan="9">No stations yet. Run Listen, or fetch PSK Reporter spots.</td></tr>';

  function label(s) {
    return "<b>" + esc(s.call) + "</b> · " + bandTxt(s.band) + "<br>" + fmtSnr(s.last_snr) + " dB · " + s.brg + "° · " + s.km.toLocaleString() + " km";
  }
  function popup(s) {
    return label(s) + "<br>" + dirTxt(s.dirs) + " · " + esc(s.mode) + " · " + ago(s.ago_min) + " ago<br><b>" + esc(s.likely_name) + "</b> " + s.likely_p + "%";
  }

  // ---------- online: Leaflet on OpenStreetMap ----------
  if (window.L) {
    var map = L.map("map", { worldCopyJump: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 12,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
    var pts = [[H.lat, H.lon]], markers = [];
    S.forEach(function (s) {
      L.polyline([[H.lat, H.lon], [s.lat, s.lon]], { color: bandCol(s.band), weight: s.dirs.length > 1 ? 4 : 2, opacity: s.online ? .85 : .35,
        dashArray: s.dirs.length === 1 && s.dirs[0] === "heard" ? "6 5" : null }).addTo(map);
    });
    L.circleMarker([H.lat, H.lon], { radius: 9, color: "#fff", weight: 2, fillColor: col("--home"), fillOpacity: 1 })
      .addTo(map).bindTooltip(esc(H.call) + " (home)", { permanent: true, direction: "right", className: "lbl" });
    S.forEach(function (s, i) {
      var m = L.circleMarker([s.lat, s.lon], { radius: 7, color: stCol(s), weight: 3, fillColor: bandCol(s.band), fillOpacity: s.online ? 1 : .45, opacity: s.online ? 1 : .7 })
        .addTo(map).bindPopup(popup(s)).bindTooltip(label(s), { permanent: true, direction: i % 2 ? "left" : "right", className: "lbl" });
      markers.push(m); pts.push([s.lat, s.lon]);
    });
    map.fitBounds(pts, { padding: [50, 50], maxZoom: 9 });
    var forced = -1;
    function tidy() {
      declutter(markers.map(function (m, i) { return { el: m.getTooltip().getElement(), prio: prio(S[i]), idx: i }; })
        .filter(function (it) { return it.el; }), forced);
    }
    map.on("zoomend moveend", function () { setTimeout(tidy, 30); });
    setTimeout(tidy, 60);
    focus = function (i) { forced = i; markers[i].openPopup(); map.panTo(markers[i].getLatLng()); setTimeout(tidy, 300); };
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
    var la0 = Math.min.apply(0, lats) - 1.5, la1 = Math.max.apply(0, lats) + 1.5, lo0 = Math.min.apply(0, lons) - 4, lo1 = Math.max.apply(0, lons) + 4;
    var k = Math.cos((la0 + la1) / 2 * Math.PI / 180), pad = 24;
    var sc = Math.min((W - 2 * pad) / ((lo1 - lo0) * k), (Hh - 2 * pad) / (la1 - la0));
    var cx = (lo0 + lo1) / 2, cy = (la0 + la1) / 2;
    function P(lat, lon) { return [W / 2 + (lon - cx) * k * sc, Hh / 2 - (lat - cy) * sc]; }
    var squares = sc >= 22 && sc * k * 2 >= 46, step = squares ? 2 : 20, vstep = squares ? 1 : 10;
    var labelGrid = squares || sc * 10 >= 26;
    var g0 = Math.floor((cx - (W / 2) / (k * sc) + 180) / step) * step - 180, g1 = cx + (W / 2) / (k * sc);
    var h0 = Math.floor((cy - (Hh / 2) / sc + 90) / vstep) * vstep - 90, h1 = cy + (Hh / 2) / sc;
    for (var lo = g0; lo <= g1; lo += step) { var a = P(0, lo); el("line", { x1: a[0], y1: 0, x2: a[0], y2: Hh, stroke: col("--grid"), "stroke-width": (lo + 180) % 20 === 0 ? 2 : 1 }); }
    for (var la = h0; la <= h1; la += vstep) { var b = P(la, 0); el("line", { x1: 0, y1: b[1], x2: W, y2: b[1], stroke: col("--grid"), "stroke-width": (la + 90) % 10 === 0 ? 2 : 1 }); }
    for (lo = g0; lo <= g1; lo += step) for (la = h0; la <= h1; la += vstep) {
      var p = P(la + vstep / 2, lo + step / 2), F = String.fromCharCode(65 + Math.floor((lo + 180) / 20)) + String.fromCharCode(65 + Math.floor((la + 90) / 10));
      var sq = step === 20 ? F : F + Math.floor(((lo + 180) % 20) / 2) + Math.floor((la + 90) % 10);
      if (labelGrid) el("text", { x: p[0], y: p[1] + 4, "text-anchor": "middle", "font-size": 11, fill: col("--grid") }, sq);
    }
    var h = P(H.lat, H.lon);
    S.slice().reverse().forEach(function (s) {
      var q = P(s.lat, s.lon);
      el("line", { x1: h[0], y1: h[1], x2: q[0], y2: q[1], stroke: bandCol(s.band), "stroke-width": s.dirs.length > 1 ? 4 : 2, opacity: s.online ? .85 : .35,
        "stroke-dasharray": s.dirs.length === 1 && s.dirs[0] === "heard" ? "7 5" : "none" });
    });
    var labels = [];
    S.forEach(function (s, i) {
      var q = P(s.lat, s.lon);
      var g = el("circle", { cx: q[0], cy: q[1], r: 7, fill: bandCol(s.band), "fill-opacity": s.online ? 1 : .45, stroke: stCol(s), "stroke-width": 3 });
      var t = document.createElementNS(NS, "title"); t.textContent = popup(s).replace(/<br>/g, "\n").replace(/<[^>]+>/g, ""); g.appendChild(t);
      var left = q[0] > W - 200, dx = left ? -12 : 12, anchor = left ? "end" : "start";
      var lg = document.createElementNS(NS, "g"); svg.appendChild(lg);
      var t1 = document.createElementNS(NS, "text"), t2 = document.createElementNS(NS, "text");
      [[t1, { x: q[0] + dx, y: q[1] - 3, "font-size": 12, "font-weight": 700, fill: col("--ink"), "text-anchor": anchor, opacity: s.online ? 1 : .7 }, s.call + " · " + bandTxt(s.band)],
       [t2, { x: q[0] + dx, y: q[1] + 11, "font-size": 11, fill: col("--muted"), "text-anchor": anchor }, fmtSnr(s.last_snr) + " dB · " + s.brg + "° · " + s.km.toLocaleString() + " km"]]
        .forEach(function (d) { for (var k2 in d[1]) d[0].setAttribute(k2, d[1][k2]); d[0].textContent = d[2]; lg.appendChild(d[0]); });
      labels.push({ el: lg, prio: prio(s), idx: i });
    });
    el("circle", { cx: h[0], cy: h[1], r: 9, fill: col("--home"), stroke: col("--panel"), "stroke-width": 2 });
    el("text", { x: h[0] + 13, y: h[1] + 4, "font-size": 13, "font-weight": 700, fill: col("--ink") }, H.call + " (home)");
    var hl = el("text", { x: h[0] + 13, y: h[1] + 4, "font-size": 13, "font-weight": 700, fill: "transparent" }, H.call + " (home)");
    labels.push({ el: hl, prio: 1e9, idx: -2 });
    declutter(labels, forced);
    hl.style.visibility = "hidden";
    el("text", { x: 10, y: Hh - 10, "font-size": 11, fill: col("--muted") }, "Offline view: Maidenhead grid. Hidden labels: click a station in the table. Connect to the internet for the OpenStreetMap view.");
  }
  var forced = -1;
  focus = function (i) { forced = i; draw(); document.getElementById("mapwrap").scrollIntoView({ behavior: "smooth" }); };
  draw();
  window.addEventListener("resize", draw);
})();
</script>
</body>
</html>
"""
