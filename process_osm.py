"""Turn raw Overpass dumps into map-ready polylines.

OSM splits a road into many short ways, so a metro area arrives as tens of
thousands of fragments. We chain ways that share an endpoint before simplifying,
which cuts the element count by an order of magnitude and makes dashed trails
render as continuous lines.
"""
import json
import math
import os
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
MI_LAT = 69.0547
ROAD_TIER = {"motorway": 0, "trunk": 0, "primary": 1, "secondary": 2, "tertiary": 2}


def make_proj(lat0, lon0):
    mi_lon = MI_LAT * math.cos(math.radians(lat0))
    return lambda lat, lon: ((lon - lon0) * mi_lon, -(lat - lat0) * MI_LAT)


def _load(fp):
    """Read an Overpass dump, tolerating an error page written in its place."""
    try:
        with open(fp, encoding="utf-8") as fh:
            els = json.load(fh).get("elements")
        return els if isinstance(els, list) else []
    except Exception as ex:
        print(f"  warning: {os.path.basename(fp)} unreadable ({ex.__class__.__name__}); "
              f"that layer will be empty")
        return []


def rdp(pts, eps):
    """Iterative Ramer-Douglas-Peucker (chains here run to thousands of nodes)."""
    n = len(pts)
    if n < 3:
        return pts
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        x0, y0 = pts[a]; x1, y1 = pts[b]
        dx, dy = x1 - x0, y1 - y0
        seg = math.hypot(dx, dy)
        worst, wi = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = (abs(dy * px - dx * py + x1 * y0 - y1 * x0) / seg) if seg else math.hypot(px - x0, py - y0)
            if d > worst:
                worst, wi = d, i
        if worst > eps:
            keep[wi] = True
            stack.append((a, wi)); stack.append((wi, b))
    return [pts[i] for i in range(n) if keep[i]]


def join_ways(segs, tol=0.004):
    """Chain segments that meet end-to-end into the longest runs we can make."""
    q = lambda p: (round(p[0] / tol), round(p[1] / tol))
    ends = defaultdict(list)
    for i, s in enumerate(segs):
        ends[q(s[0])].append(i)
        ends[q(s[-1])].append(i)
    used = [False] * len(segs)
    out = []
    for i in range(len(segs)):
        if used[i]:
            continue
        used[i] = True
        chain = list(segs[i])
        growing = True
        while growing:
            growing = False
            for at_tail in (True, False):
                p = chain[-1] if at_tail else chain[0]
                for j in ends.get(q(p), ()):
                    if used[j]:
                        continue
                    s = segs[j]
                    if at_tail:
                        if q(s[0]) == q(p):
                            add = s[1:]
                        elif q(s[-1]) == q(p):
                            add = s[-2::-1]
                        else:
                            continue
                        chain.extend(add)
                    else:
                        if q(s[-1]) == q(p):
                            pre = s[:-1]
                        elif q(s[0]) == q(p):
                            pre = s[:0:-1]
                        else:
                            continue
                        chain[0:0] = pre
                    used[j] = True
                    growing = True
                    break
        out.append(chain)
    return out


def clip_circle(pts, r):
    """Split a polyline into the runs that fall inside the circle (1-node margin)."""
    runs, cur = [], []
    inside = [math.hypot(x, y) <= r for x, y in pts]
    n = len(pts)
    for i, p in enumerate(pts):
        near = inside[i] or (i > 0 and inside[i - 1]) or (i < n - 1 and inside[i + 1])
        if near:
            cur.append(p)
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    return [r_ for r_ in runs if len(r_) >= 2]


def finish(raw, eps, radius, q=2):
    """Chain, clip to the survey circle, simplify, quantise."""
    out = []
    for chain in join_ways(raw):
        for run in clip_circle(chain, radius + 0.6):
            s = rdp(run, eps)
            if len(s) >= 2:
                out.append([[round(x, q), round(y, q)] for x, y in s])
    return out


def build(lat0, lon0, radius, osmdir=None):
    osmdir = osmdir or os.path.join(HERE, "osm")
    proj = make_proj(lat0, lon0)
    raw = {k: [] for k in ("hw0", "hw1", "rd", "trmaj", "trmin", "riv")}
    names = []

    def geom(e):
        return [proj(g["lat"], g["lon"]) for g in (e.get("geometry") or [])]

    for e in _load(os.path.join(osmdir, "roads.json")):
        hw = (e.get("tags") or {}).get("highway", "")
        if hw.endswith("_link"):
            continue
        t = ROAD_TIER.get(hw)
        if t is None:
            continue
        pts = geom(e)
        if len(pts) >= 2:
            raw[["hw0", "hw1", "rd"][t]].append(pts)

    seen = set()
    for e in _load(os.path.join(osmdir, "routes.json")):
        nm = (e.get("tags") or {}).get("name", "")
        for m in e.get("members", []):
            g = m.get("geometry")
            if not g:
                continue
            pts = [proj(p["lat"], p["lon"]) for p in g]
            if len(pts) < 2:
                continue
            key = (round(pts[0][0], 2), round(pts[0][1], 2),
                   round(pts[-1][0], 2), round(pts[-1][1], 2))
            if key in seen:
                continue
            seen.add(key)
            raw["trmaj"].append(pts)
        if nm:
            names.append(nm)

    for e in _load(os.path.join(osmdir, "trails.json")):
        pts = geom(e)
        if len(pts) < 2:
            continue
        key = (round(pts[0][0], 2), round(pts[0][1], 2),
               round(pts[-1][0], 2), round(pts[-1][1], 2))
        if key in seen:
            continue
        raw["trmin"].append(pts)

    for e in _load(os.path.join(osmdir, "rivers.json")):
        pts = geom(e)
        if len(pts) >= 2:
            raw["riv"].append(pts)

    eps = {"hw0": .008, "hw1": .008, "rd": .012, "trmaj": .012, "trmin": .015, "riv": .012}
    layers = {k: finish(v, eps[k], radius) for k, v in raw.items()}

    # Dense metros still overwhelm the renderer; thin the minor layers there.
    for key, floor in (("rd", 0.05), ("trmin", 0.05), ("hw1", 0.03)):
        if len(layers[key]) > 9000:
            before = len(layers[key])
            layers[key] = [ln for ln in layers[key] if _length(ln) >= floor]
            print(f"  {key}: dropped {before - len(layers[key])} stubs under {floor} mi "
                  f"({before} -> {len(layers[key])})")
    return layers, sorted(set(names))


def _length(ln):
    return sum(math.hypot(ln[i + 1][0] - ln[i][0], ln[i + 1][1] - ln[i][1])
               for i in range(len(ln) - 1))


if __name__ == "__main__":
    L, names = build(38.2522778, -105.6681389, 50.0)
    for k, v in L.items():
        print(f"  {k:<6} {len(v):>6} lines  {sum(len(s) for s in v):>7} pts")
    print("named routes:", len(names))
