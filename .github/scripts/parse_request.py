"""Read a survey request, validate it, and say whether it needs building.

The request arrives either as workflow_dispatch inputs or as the body of a
GitHub issue opened by the map page. Both land here as environment variables so
that nothing a stranger typed is ever pasted into a shell command.

Writes ok / reason / at / lat / lon / radius / spacing / name to $GITHUB_OUTPUT.
"""
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from coords import parse as parse_coord, fmt as fmt_coord   # noqa: E402

MIN_RADIUS, MAX_RADIUS = 5.0, 100.0
MIN_SPACING, MAX_SPACING = 1.0, 10.0
MAX_POINTS = 3000          # about 3.6 * (radius / spacing) ** 2 samples
NAME_OK = re.compile(r"[^A-Za-z0-9 ,.'\-/()]")


def field(body, key):
    """Pull `key: value` out of an issue body, fences and bullets and all."""
    m = re.search(r"(?im)^[\s>*\-]*" + key + r"\s*[:=]\s*(.+?)\s*$", body)
    return m.group(1).strip().strip("`\"'") if m else ""


def miles(lat1, lon1, lat2, lon2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def number(text, default, lo, hi, label):
    if not text:
        return default, ""
    try:
        v = float(re.sub(r"[^0-9.\-]", "", text))
    except ValueError:
        return None, f"`{label}` is not a number."
    if not lo <= v <= hi:
        return None, f"`{label}` has to be between {lo:g} and {hi:g}; got {v:g}."
    return v, ""


def emit(**kw):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
        for k, v in kw.items():
            print(k, ' '.join(str(v).split()), sep='=', file=fh)
    print(json.dumps(kw, indent=1))


def stop(reason):
    emit(ok="false", reason=reason)
    sys.exit(0)


def main():
    event = os.environ.get("EVENT", "workflow_dispatch")
    if event == "issues":
        body = os.environ.get("ISSUE_BODY", "")
        raw_at = field(body, "at") or field(body, "coordinate")
        raw_radius = field(body, "radius")
        raw_spacing = field(body, "spacing")
        raw_name = field(body, "name")
    else:
        raw_at = os.environ.get("IN_AT", "")
        raw_radius = os.environ.get("IN_RADIUS", "")
        raw_spacing = os.environ.get("IN_SPACING", "")
        raw_name = os.environ.get("IN_NAME", "")

    if not raw_at:
        stop("No coordinate in the request. The body needs a line like `at: 39.7392, -104.9847`.")
    if len(raw_at) > 80:
        stop("That coordinate line is too long to be a coordinate.")
    try:
        lat, lon = parse_coord(raw_at)
    except Exception as ex:
        stop(f"Could not read a coordinate from `{raw_at[:60]}` ({ex}).")

    if not (17.5 <= lat <= 72.0 and -180.0 <= lon <= -64.0):
        stop(f"{fmt_coord(lat, lon)} is outside the United States, so the FCC has no data for it.")

    radius, err = number(raw_radius, 50.0, MIN_RADIUS, MAX_RADIUS, "radius")
    if err:
        stop(err)
    spacing, err = number(raw_spacing, 2.5, MIN_SPACING, MAX_SPACING, "spacing")
    if err:
        stop(err)

    points = 3.6 * (radius / spacing) ** 2
    if points > MAX_POINTS:
        stop(f"A {radius:g} mi radius at {spacing:g} mi spacing is about {points:,.0f} sample "
             f"points, over the {MAX_POINTS:,} cap. Widen the spacing or shrink the radius.")

    name = NAME_OK.sub("", raw_name)[:60].strip()

    man_path = os.path.join(ROOT, "surveys.json")
    man = json.load(open(man_path, encoding="utf-8")) if os.path.exists(man_path) else {}
    for s in man.get("surveys", []):
        d = miles(lat, lon, s["center"][0], s["center"][1])
        if d <= s["radius"] and radius <= s["radius"]:
            stop(f"**{s['name']}** already covers that point ({d:.0f} mi from its centre). "
                 f"Open it at https://jsantiago20-cyb.github.io/fcc-signal-map/"
                 f"?at={lat:.6f},{lon:.6f}")

    emit(ok="true", reason="", at=f"{lat:.6f}, {lon:.6f}",
         lat=f"{lat:.6f}", lon=f"{lon:.6f}",
         radius=f"{radius:g}", spacing=f"{spacing:g}", name=name,
         points=f"{points:,.0f}", pretty=fmt_coord(lat, lon))


if __name__ == "__main__":
    main()
