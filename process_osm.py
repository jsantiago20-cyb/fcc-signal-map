"""Clip, simplify and quantise the raw Overpass dumps into map-ready polylines."""
import json, math, os

HERE = os.path.dirname(os.path.abspath(__file__))
MI_LAT = 69.0547


def make_proj(lat0, lon0):
    mi_lon = MI_LAT * math.cos(math.radians(lat0))
    def proj(lat, lon):
        return ((lon - lon0) * mi_lon, -(lat - lat0) * MI_LAT)
    return proj


def rdp(pts, eps):
    """Iterative Ramer-Douglas-Peucker (ways here run to thousands of nodes)."""
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


def clip_circle(pts, r):
    """Split a polyline into the runs that fall inside the circle (1-node margin)."""
    runs, cur = [], []
    inside = [math.hypot(x, y) <= r for x, y in pts]
    for i, p in enumerate(pts):
        near = inside[i] or (i > 0 and inside[i-1]) or (i < len(pts)-1 and inside[i+1])
        if near:
            cur.append(p)
        elif cur:
            runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    return [r_ for r_ in runs if len(r_) >= 2]


def emit(pts, eps, r, out, q=2):
    for run in clip_circle(pts, r):
        s = rdp(run, eps)
        if len(s) >= 2:
            out.append([[round(x, q), round(y, q)] for x, y in s])


ROAD_TIER = {"motorway":0,"trunk":0,"primary":1,"secondary":2,"tertiary":2}


def build(lat0, lon0, radius, osmdir=None):
    osmdir = osmdir or os.path.join(HERE, "osm")
    proj = make_proj(lat0, lon0)
    R = radius + 0.6
    layers = {"hw0": [], "hw1": [], "rd": [], "trmaj": [], "trmin": [], "riv": []}
    names = []

    fp = os.path.join(osmdir, "roads.json")
    if os.path.exists(fp):
        for e in json.load(open(fp, encoding="utf-8"))["elements"]:
            hw = (e.get("tags") or {}).get("highway", "")
            if hw.endswith("_link"):
                continue
            t = ROAD_TIER.get(hw)
            if t is None:
                continue
            pts = [proj(g["lat"], g["lon"]) for g in (e.get("geometry") or [])]
            if len(pts) < 2:
                continue
            emit(pts, .008 if t < 2 else .012, R, layers[["hw0","hw1","rd"][t]])

    fp = os.path.join(osmdir, "routes.json")
    seen = set()
    if os.path.exists(fp):
        for e in json.load(open(fp, encoding="utf-8"))["elements"]:
            nm = (e.get("tags") or {}).get("name", "")
            for m in e.get("members", []):
                g = m.get("geometry")
                if not g:
                    continue
                pts = [proj(p["lat"], p["lon"]) for p in g]
                if len(pts) < 2:
                    continue
                key = (round(pts[0][0],2), round(pts[0][1],2), round(pts[-1][0],2), round(pts[-1][1],2))
                if key in seen:
                    continue
                seen.add(key)
                emit(pts, .012, R, layers["trmaj"])
            if nm:
                names.append(nm)

    fp = os.path.join(osmdir, "trails.json")
    if os.path.exists(fp):
        for e in json.load(open(fp, encoding="utf-8"))["elements"]:
            pts = [proj(g["lat"], g["lon"]) for g in (e.get("geometry") or [])]
            if len(pts) < 2:
                continue
            key = (round(pts[0][0],2), round(pts[0][1],2), round(pts[-1][0],2), round(pts[-1][1],2))
            if key in seen:
                continue
            emit(pts, .015, R, layers["trmin"])

    fp = os.path.join(osmdir, "rivers.json")
    if os.path.exists(fp):
        try:
            for e in json.load(open(fp, encoding="utf-8"))["elements"]:
                pts = [proj(g["lat"], g["lon"]) for g in (e.get("geometry") or [])]
                if len(pts) >= 2:
                    emit(pts, .012, R, layers["riv"])
        except Exception:
            pass

    return layers, sorted(set(names))


if __name__ == "__main__":
    L, names = build(38.2522778, -105.6681389, 50.0)
    tot = 0
    for k, v in L.items():
        pts = sum(len(s) for s in v)
        tot += pts
        print(f"  {k:<6} {len(v):>5} lines  {pts:>7} pts")
    print("total points:", tot)
    print("named routes:", len(names))
    j = json.dumps(L, separators=(",", ":"))
    print("json bytes:", f"{len(j):,}")
    open(os.path.join(HERE, "osm_layers.json"), "w", encoding="utf-8").write(j)
