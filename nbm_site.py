#!/usr/bin/env python3
"""Build a zoomable FCC mobile-coverage map for any point.

    python nbm_site.py --at "38.25228 N 105.66813 W"
    python nbm_site.py --at "(38.2461363, -105.6641888)" --radius 40 --spacing 2
    python nbm_site.py --at "39.7392, -104.9847" --name "Denver Signal Map"

Everything is cached under sites/<slug>/, so re-runs only fetch what is missing.
Pass --force coverage,osm,terrain,census to refetch a stage.

Stages
  census    county outlines + place centroids   (Census TIGERweb)
  terrain   hillshade raster                    (USGS 3DEP)
  osm       roads / trails / rivers             (OpenStreetMap Overpass)
  coverage  the FCC mobile location summaries   (broadbandmap.fcc.gov, via Chrome)
"""
import argparse, base64, json, math, os, re, shutil, subprocess, sys, tempfile, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from coords import parse as parse_coord, fmt as fmt_coord, CoordError   # noqa: E402
import process_osm                                                       # noqa: E402

MI_LAT = 69.0547
UA = "nbm-site/1.0 (personal coverage research)"
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


# ----------------------------------------------------------------- helpers
def curl(url, out=None, post=None, timeout=300, headers=None):
    cmd = ["curl", "-sS", "-m", str(timeout), "-A", UA, "-L"]
    for h in (headers or []):
        cmd += ["-H", h]
    if post is not None:
        cmd += ["-X", "POST", "--data", post]
    if out:
        cmd += ["-o", out]
    cmd += ["-w", "%{http_code}", url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    code = (r.stdout or "").strip().splitlines()[-1] if r.stdout else "000"
    return code, (r.stdout or "")


def proj_factory(lat0, lon0):
    mi_lon = MI_LAT * math.cos(math.radians(lat0))
    return lambda la, lo: ((lo - lon0) * mi_lon, -(la - lat0) * MI_LAT), mi_lon


def bbox_for(lat0, lon0, radius):
    dlat = radius / MI_LAT
    dlon = radius / (MI_LAT * math.cos(math.radians(lat0)))
    return (lat0 - dlat, lon0 - dlon, lat0 + dlat, lon0 + dlon)


def hex_lattice(lat0, lon0, radius, spacing):
    mi_lon = MI_LAT * math.cos(math.radians(lat0))
    dlat = spacing * math.sqrt(3) / 2 / MI_LAT
    nrows = int(radius / (spacing * math.sqrt(3) / 2)) + 1
    pts = []
    for r in range(-nrows, nrows + 1):
        lat = lat0 + r * dlat
        yoff = (lat - lat0) * MI_LAT
        if abs(yoff) > radius:
            continue
        half = math.sqrt(max(radius ** 2 - yoff ** 2, 0.0))
        ncols = int(half / spacing) + 1
        shift = 0.5 * spacing if (r % 2) else 0.0
        for c in range(-ncols, ncols + 1):
            xoff = c * spacing + shift
            if math.hypot(xoff, yoff) > radius:
                continue
            pts.append((round(lat, 6), round(lon0 + xoff / mi_lon, 6)))
    return pts


# ----------------------------------------------------------------- stages
def stage_census(d, lat0, lon0, radius):
    cfile, pfile = os.path.join(d, "counties.json"), os.path.join(d, "places_raw.json")
    s, w, n, e = bbox_for(lat0, lon0, radius)
    bbox = f"{w},{s},{e},{n}"
    base = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb"
    q = ("where=1%3D1&outFields=BASENAME&geometry=" + urllib.parse.quote(bbox) +
         "&geometryType=esriGeometryEnvelope&inSR=4326&spatialRel=esriSpatialRelIntersects"
         "&outSR=4326&f=geojson")
    print("  counties ...", end=" ", flush=True)
    print(curl(f"{base}/State_County/MapServer/1/query?{q}", cfile)[0])
    out = []
    for lyr in (4, 5):
        tmp = os.path.join(d, f"_p{lyr}.json")
        q2 = ("where=1%3D1&outFields=BASENAME,CENTLAT,CENTLON,AREALAND&geometry=" +
              urllib.parse.quote(bbox) + "&geometryType=esriGeometryEnvelope&inSR=4326"
              "&spatialRel=esriSpatialRelIntersects&returnGeometry=false&f=json")
        print(f"  places layer {lyr} ...", end=" ", flush=True)
        print(curl(f"{base}/Places_CouSub_ConCity_SubMCD/MapServer/{lyr}/query?{q2}", tmp)[0])
        try:
            for f in json.load(open(tmp, encoding="utf-8")).get("features", []):
                a = f["attributes"]
                try:
                    out.append({"n": a["BASENAME"], "lat": float(a["CENTLAT"]),
                                "lon": float(a["CENTLON"]), "a": float(a.get("AREALAND") or 0)})
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
    json.dump(out, open(pfile, "w", encoding="utf-8"))
    print(f"  -> {len(out)} places")


def stage_terrain(d, lat0, lon0, radius, px=3600):
    raw = os.path.join(d, "_hillshade.png")
    s, w, n, e = bbox_for(lat0, lon0, radius)
    # request at the plate-carree aspect so the image maps linearly onto the projection
    aspect = (e - w) / (n - s)
    size = f"{px},{round(px/aspect)}"
    url = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer"
           "/exportImage?bbox=" + f"{w},{s},{e},{n}" +
           "&bboxSR=4326&imageSR=4326&size=" + size + "&format=png"
           "&renderingRule=" + urllib.parse.quote('{"rasterFunction":"Hillshade Gray"}') +
           "&f=image")
    print("  hillshade ...", end=" ", flush=True)
    print(curl(url, raw, timeout=300)[0], end=" ")
    try:
        from PIL import Image
        im = Image.open(raw).convert("L")
        im.save(os.path.join(d, "terrain.webp"), "WEBP", quality=58, method=5)
        print(f"{im.size[0]}x{im.size[1]} -> {os.path.getsize(os.path.join(d,'terrain.webp')):,} b")
    except Exception as ex:
        print("PIL failed:", ex)
    finally:
        if os.path.exists(raw):
            os.remove(raw)


def stage_osm(d, lat0, lon0, radius, force=False):
    od = os.path.join(d, "osm")
    os.makedirs(od, exist_ok=True)
    s, w, n, e = bbox_for(lat0, lon0, radius)
    bb = f"{s},{w},{n},{e}"
    jobs = {
        "roads":  f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)(_link)?$"]({bb});',
        "trails": f'way["highway"~"^(path|track|bridleway)$"]["name"]({bb});',
        "rivers": f'way["waterway"="river"]({bb});',
        "routes": f'relation["route"="hiking"]["name"]({bb});',
    }

    def usable(fp):
        try:
            with open(fp, encoding="utf-8") as fh:
                return isinstance(json.load(fh).get("elements"), list)
        except Exception:
            return False

    for name, body in jobs.items():
        fp = os.path.join(od, f"{name}.json")
        if not force and os.path.exists(fp) and usable(fp):
            print(f"  osm {name} cached")
            continue
        data = "data=" + urllib.parse.quote(f"[out:json][timeout:300];({body});out geom;")
        got = False
        for attempt in range(2):                       # each host twice; Overpass 504s under load
            for host in OVERPASS:
                print(f"  osm {name} @ {host.split('/')[2]} ...", end=" ", flush=True)
                code, _ = curl(host, fp, post=data, timeout=300)
                sz = os.path.getsize(fp) if os.path.exists(fp) else 0
                good = code == "200" and usable(fp)
                print(f"{code} {sz:,}b {'ok' if good else 'unusable'}")
                if good:
                    got = True
                    break
                time.sleep(6)
            if got:
                break
        if not got:
            # a layer we could not fetch is an empty layer, not a failed build
            json.dump({"elements": []}, open(fp, "w", encoding="utf-8"))
            print(f"  osm {name}: giving up, layer will be empty")


def stage_coverage(d, lat0, lon0, radius, spacing):
    """Harvest the FCC location summaries through a real Chrome session."""
    from cdp import Chrome
    out = os.path.join(d, "coverage.json")
    have, blob = set(), {"points": []}
    if os.path.exists(out):
        blob = json.load(open(out, encoding="utf-8"))
        have = {(p["lat"], p["lon"]) for p in blob["points"]}
    todo = [p for p in hex_lattice(lat0, lon0, radius, spacing) if p not in have]
    print(f"  lattice {len(have)+len(todo)} points, {len(todo)} to fetch")
    if not todo:
        return blob

    JS = r"""
    (async () => {
      const pts = __PTS__, uuid = "__UUID__";
      const out = new Array(pts.length).fill(null);
      let i = 0;
      const worker = async () => {
        while (true) {
          const kk = i++;
          if (kk >= pts.length) return;
          const la = pts[kk][0], lo = pts[kk][1];
          for (let a = 0; a < 3; a++) {
            try {
              const r = await fetch(`/nbm/map/api/mobile/detail/${uuid}/${la}/${lo}`,
                                    {credentials:'include'});
              if (r.ok) { const j = await r.json(); out[kk] = j.data || []; break; }
            } catch (e) {}
            await new Promise(s => setTimeout(s, 400*(a+1)));
          }
        }
      };
      await Promise.all(Array.from({length: 4}, worker));
      return JSON.stringify(out);
    })()
    """
    session = 0
    while todo and session < 10:
        session += 1
        prof = os.path.join(tempfile.gettempdir(), f"nbm_h{session}")
        shutil.rmtree(prof, ignore_errors=True)
        ch = Chrome(port=9600 + session, profile=prof)
        got = []
        try:
            ch.navigate("https://broadbandmap.fcc.gov/home", settle=16)
            if not blob.get("process_uuid"):
                fl = json.loads(ch.eval("fetch('/nbm/map/api/published/filing',"
                                        "{credentials:'include'}).then(r=>r.text())"))["data"]
                def key(r):
                    s = r["filing_subtype"].replace(",", "").split()
                    return (int(s[-1]), 12 if s[0] == "December" else 6)
                latest = max(fl, key=key)
                blob["process_uuid"] = latest["process_uuid"]
                blob["vintage"] = latest["filing_subtype"]
                mo, _, yr = blob["vintage"].replace(",", "").split()
                blob["verslug"] = ("dec" if mo == "December" else "jun") + yr
                print(f"  vintage {blob['vintage']}  uuid {blob['process_uuid']}")
            for s0 in range(0, len(todo), 30):
                chunk = todo[s0:s0 + 30]
                expr = (JS.replace("__PTS__", json.dumps(chunk))
                          .replace("__UUID__", blob["process_uuid"]))
                res = json.loads(ch.eval(expr, timeout=180))
                hits = 0
                for pt, rows in zip(chunk, res):
                    if rows is not None:
                        blob["points"].append({"lat": pt[0], "lon": pt[1], "rows": rows})
                        got.append(pt); hits += 1
                if hits == 0:
                    print(f"  session {session} flagged at {len(blob['points'])} pts; rotating")
                    break
                if (s0 // 30) % 8 == 0:
                    print(f"    {len(blob['points'])} points", flush=True)
                time.sleep(.8)
        except Exception as ex:
            print("  session error:", str(ex)[:140])
        finally:
            ch.close(); shutil.rmtree(prof, ignore_errors=True)
        todo = [p for p in todo if p not in set(got)]
        json.dump(blob, open(out, "w", encoding="utf-8"))
        if todo:
            time.sleep(4)
    print(f"  coverage: {len(blob['points'])} points, {len(todo)} unrecoverable")
    return blob


# ----------------------------------------------------------------- assemble
def rdp(pts, eps):
    return process_osm.rdp(pts, eps)


def build_payload(d, lat0, lon0, radius, spacing, elev):
    proj, _ = proj_factory(lat0, lon0)
    blob = json.load(open(os.path.join(d, "coverage.json"), encoding="utf-8"))

    carriers, seen = [], set()
    for p in blob["points"]:
        for r in p["rows"]:
            if r["brandname"] not in seen:
                seen.add(r["brandname"]); carriers.append((r["brandname"], 0))
    counts = {c: 0 for c, _ in carriers}
    for p in blob["points"]:
        for r in p["rows"]:
            counts[r["brandname"]] += 1
    carriers = [c for c, _ in sorted(carriers, key=lambda t: -counts[t[0]])]

    pts = []
    for p in blob["points"]:
        per = {c: [0, 0, 0, 0] for c in carriers}
        for r in p["rows"]:
            c = r["brandname"]
            if c not in per:
                continue
            s, t = int(r["minsignal"]), r["technology_type"]
            if t == "3G":
                per[c][0] = s
            elif t == "4G LTE":
                per[c][1] = s
            elif t == "5G-NR":
                tier = 35 if float(r["mindown"]) >= 35 else 7
                if tier >= per[c][3]:
                    per[c][2], per[c][3] = s, tier
        x, y = proj(p["lat"], p["lon"])
        flat = []
        for c in carriers:
            flat += per[c]
        pts.append([round(x, 3), round(y, 3), round(p["lat"], 5), round(p["lon"], 5)] + flat)

    counties = []
    try:
        for f in json.load(open(os.path.join(d, "counties.json"), encoding="utf-8"))["features"]:
            g = f["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            rings = []
            for poly in polys:
                ring = [proj(la, lo) for lo, la in poly[0]]
                ring = [q for q in ring if abs(q[0]) < radius * 1.4 and abs(q[1]) < radius * 1.4]
                if len(ring) < 4:
                    continue
                ring = rdp(ring, radius * 0.0044)
                if len(ring) >= 4:
                    rings.append([[round(a, 2), round(b, 2)] for a, b in ring])
            if rings:
                counties.append({"n": f["properties"].get("BASENAME"), "r": rings})
    except Exception:
        pass

    raw = json.load(open(os.path.join(d, "places_raw.json"), encoding="utf-8"))
    raw.sort(key=lambda q: -q["a"])
    places, tiers = [], [(radius * 0.13, 0, 22), (radius * 0.06, 1, 30), (radius * 0.028, 2, 44)]
    for gap, tier, cap in tiers:
        added = 0
        for q in raw:
            x, y = proj(q["lat"], q["lon"])
            if math.hypot(x, y) > radius - 1.5:
                continue
            if any(math.hypot(x - k["x"], y - k["y"]) < gap for k in places):
                continue
            places.append({"n": q["n"], "x": round(x, 2), "y": round(y, 2), "t": tier})
            added += 1
            if added >= cap:
                break

    osm_layers, _ = process_osm.build(lat0, lon0, radius, osmdir=os.path.join(d, "osm"))

    return {"vintage": blob.get("vintage", "unknown"), "verslug": blob.get("verslug", "dec2025"),
            "uuid": blob.get("process_uuid"), "center": [lat0, lon0], "radius": radius,
            "spacing": spacing, "elev": elev, "carriers": carriers, "pts": pts,
            "counties": counties, "places": places, "osm": osm_layers}


def write_pack(slug, name, payload, cache_dir):
    """Publish a survey as surveys/<slug>/{data.json,terrain.webp} + refresh surveys.json."""
    pack = os.path.join(HERE, "surveys", slug)
    os.makedirs(pack, exist_ok=True)
    json.dump(payload, open(os.path.join(pack, "data.json"), "w", encoding="utf-8"),
              separators=(",", ":"))
    shutil.copy(os.path.join(cache_dir, "terrain.webp"), os.path.join(pack, "terrain.webp"))

    man_path = os.path.join(HERE, "surveys.json")
    man = {"surveys": []}
    if os.path.exists(man_path):
        try:
            man = json.load(open(man_path, encoding="utf-8"))
        except Exception:
            pass
    entry = {"slug": slug, "name": name, "center": payload["center"],
             "radius": payload["radius"], "spacing": payload["spacing"],
             "vintage": payload["vintage"], "verslug": payload["verslug"],
             "elev": payload["elev"], "points": len(payload["pts"]),
             "carriers": payload["carriers"]}
    man["surveys"] = [s for s in man.get("surveys", []) if s.get("slug") != slug] + [entry]
    man["surveys"].sort(key=lambda s: s["name"])
    man.setdefault("default", man["surveys"][0]["slug"])
    json.dump(man, open(man_path, "w", encoding="utf-8"), indent=1)
    size = os.path.getsize(os.path.join(pack, "data.json"))
    print(f"  pack surveys/{slug}/  data.json {size:,} b + terrain.webp")
    print(f"  manifest now lists {len(man['surveys'])} survey(s)")
    return pack


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", required=True, help='any coordinate format, e.g. "38.25228N 105.66813W"')
    ap.add_argument("--radius", type=float, default=50.0)
    ap.add_argument("--spacing", type=float, default=2.5)
    ap.add_argument("--name")
    ap.add_argument("--slug")
    ap.add_argument("--force", default="", help="comma list: census,terrain,osm,coverage")
    ap.add_argument("--out", help="unused; packs go to surveys/<slug>/")
    a = ap.parse_args()

    try:
        lat0, lon0 = parse_coord(a.at)
    except CoordError as ex:
        sys.exit(f"could not read --at: {ex}")
    print(f"center {fmt_coord(lat0, lon0)}  radius {a.radius} mi  spacing {a.spacing} mi")

    county, elev = None, None
    try:
        _, txt = curl(f"https://geo.fcc.gov/api/census/area?lat={lat0}&lon={lon0}&format=json")
        res = json.loads(txt[:-3])["results"][0]
        county = res["county_name"]
        st = res.get("state_code") or res.get("state_name")
        if st:
            county = f"{county}, {st}"
    except Exception:
        pass
    try:
        _, txt = curl(f"https://epqs.nationalmap.gov/v1/json?x={lon0}&y={lat0}&units=Feet&wkid=4326")
        elev = float(json.loads(txt[:-3])["value"])
    except Exception:
        pass
    title = a.name or (county if county else "Survey")
    slug = a.slug or re.sub(r"_+", "_",
                        "".join(ch if ch.isalnum() else "_" for ch in title.lower())).strip("_")
    d = os.path.join(HERE, "sites", slug)
    os.makedirs(d, exist_ok=True)
    print(f"title '{title}'  dir sites/{slug}"
          + (f"  elev {elev:,.0f} ft" if elev else ""))

    force = {x.strip() for x in a.force.split(",") if x.strip()}
    if "census" in force or not os.path.exists(os.path.join(d, "places_raw.json")):
        print(" [census]"); stage_census(d, lat0, lon0, a.radius)
    if "terrain" in force or not os.path.exists(os.path.join(d, "terrain.webp")):
        print(" [terrain]"); stage_terrain(d, lat0, lon0, a.radius)
    if True:   # stage_osm decides per layer what is cached
        print(" [osm]"); stage_osm(d, lat0, lon0, a.radius, force="osm" in force)
    print(" [coverage]"); stage_coverage(d, lat0, lon0, a.radius, a.spacing)

    print(" [assemble]")
    payload = build_payload(d, lat0, lon0, a.radius, a.spacing, elev)
    n_osm = sum(len(v) for v in payload["osm"].values())
    print(f"  {len(payload['pts'])} coverage points, {n_osm} osm lines, "
          f"{len(payload['places'])} places, {len(payload['counties'])} counties")
    write_pack(slug, title, payload, d)
    subprocess.run([sys.executable, os.path.join(HERE, "build_app.py")], check=False)


if __name__ == "__main__":
    main()
