"""Parse latitude/longitude out of the formats people actually paste.

Handles, among others:
    (38.2461363, -105.6641888)
    38.2461363, -105.6641888
    38.2461363 -105.6641888
    38.25228 N 105.66813 W          (with or without degree marks)
    N 38 15 08.2  W 105 40 05.3     (deg/min/sec)
    38.25228, -105.66813
"""
import re

_HEMI = re.compile(r"[NSEWnsew]")
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
_CLEAN = re.compile(r"[()\[\]°º‘’′'“”″\"]")


class CoordError(ValueError):
    pass


def parse(text):
    """Return (lat, lon) as floats, or raise CoordError."""
    if text is None:
        raise CoordError("no coordinate given")
    s = _CLEAN.sub(" ", str(text).strip())
    if not s:
        raise CoordError("no coordinate given")

    hemis = [(m.group(0).upper(), m.start()) for m in _HEMI.finditer(s)]
    nums = [(float(m.group(0)), m.start()) for m in _NUM.finditer(s)]
    if len(nums) < 2:
        raise CoordError("need two numbers, found %d" % len(nums))

    if hemis:
        ns = [h for h in hemis if h[0] in "NS"]
        ew = [h for h in hemis if h[0] in "EW"]
        if not ns or not ew:
            hemis = []                       # only one axis marked -> treat as plain decimal

    if hemis:
        # A hemisphere letter either leads its numbers ("N 38 15 08") or trails them
        # ("38.25228 N"). Decide once from the first letter, then let each letter own
        # the run of numbers on that side of it.
        leading = hemis[0][1] < nums[0][1]
        positions = [p for _, p in hemis]
        groups = {}
        for letter, pos in hemis:
            if leading:
                nxt = min([p for p in positions if p > pos], default=float("inf"))
                span = [v for v, p in nums if pos < p < nxt]
            else:
                prv = max([p for p in positions if p < pos], default=float("-inf"))
                span = [v for v, p in nums if prv < p < pos]
            groups.setdefault(letter, []).extend(span)
        lat = _dms(groups.get("N") or groups.get("S") or [])
        lon = _dms(groups.get("E") or groups.get("W") or [])
        if lat is None or lon is None:
            raise CoordError("could not split the two coordinates")
        if "S" in groups:
            lat = -abs(lat)
        if "W" in groups:
            lon = -abs(lon)
    else:
        vals = [v for v, _ in nums]
        if len(vals) in (4, 6):              # DMS without hemisphere letters
            half = len(vals) // 2
            lat, lon = _dms(vals[:half]), _dms(vals[half:])
        else:
            lat, lon = vals[0], vals[1]

    if abs(lat) > 90 and abs(lon) <= 90:     # pasted lon-first
        lat, lon = lon, lat
    if abs(lat) > 90 or abs(lon) > 180:
        raise CoordError("out of range: %.6f, %.6f" % (lat, lon))
    return lat, lon


def _dms(vals):
    if not vals:
        return None
    sign = -1.0 if vals[0] < 0 else 1.0
    out = abs(vals[0])
    if len(vals) > 1:
        out += abs(vals[1]) / 60.0
    if len(vals) > 2:
        out += abs(vals[2]) / 3600.0
    return sign * out


def fmt(lat, lon, dp=6):
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.{dp}f}°{ns} {abs(lon):.{dp}f}°{ew}"


if __name__ == "__main__":
    tests = [
        "(38.2461363, -105.6641888)",
        "38.2461363, -105.6641888",
        "38.25228°N 105.66813°W",
        "38.25228 N, 105.66813 W",
        "N38 15 8.2 W105 40 5.3",
        "38.2461363 -105.6641888",
        "-105.6641888, 38.2461363",
    ]
    for t in tests:
        try:
            la, lo = parse(t)
            print(f"  {t:<32} -> {la:.7f}, {lo:.7f}   ({fmt(la, lo, 5)})")
        except CoordError as e:
            print(f"  {t:<32} -> ERROR {e}")
