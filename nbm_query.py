#!/usr/bin/env python3
"""
nbm_query.py -- replicate the FCC National Broadband Map "Location Summary -> Mobile"
lookup by calling the same JSON API the website itself calls.

Why Chrome: broadbandmap.fcc.gov sits behind Akamai Bot Manager. curl/requests get a
403 nginx challenge no matter what headers you send. Headless Chrome executes the
bot-manager JS, earns the _abck cookie in a persistent profile, and then the API
answers normally.

Endpoints replicated (captured from the live site via chrome --log-net-log):
  GET /nbm/map/api/published/filing
        -> list of published data vintages + their process_uuid
  GET /nbm/map/api/mobile/detail/{process_uuid}/{lat}/{lon}
        -> providers/technologies covering that point  (this is the sidebar table)
  GET /api/reference/map_processing_updates/{process_uuid}
        -> fabric vintage + last_updated_date

Usage:
  python nbm_query.py --lat 38.25228 --lon -105.66813
  python nbm_query.py --lat 38.25228 --lon -105.66813 --version all --csv out.csv
"""
import argparse, csv, html, json, os, re, subprocess, sys, tempfile

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36")
BASE = "https://broadbandmap.fcc.gov"
PROFILE = os.path.join(tempfile.gettempdir(), "nbm_chrome_profile")

# BDC mobile technology codes
TECH = {400: "4G LTE", 500: "5G-NR", 300: "3G"}


def chrome_path():
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    sys.exit("Chrome not found - install Chrome or edit CHROME_CANDIDATES.")


def fetch(url, budget=9000, timeout=90):
    """Fetch a URL through headless Chrome and return the response body text."""
    cmd = [chrome_path(), "--headless=old", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", f"--user-data-dir={PROFILE}",
           f"--user-agent={UA}", f"--virtual-time-budget={budget}",
           "--dump-dom", url]
    try:
        dom = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout, errors="replace").stdout
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"(?is)<pre[^>]*>(.*?)</pre>", dom)          # JSON viewer wraps in <pre>
    if m:
        return html.unescape(re.sub(r"(?s)<[^>]+>", "", m.group(1)))
    if "403" in dom or "Access Denied" in dom:
        return None
    return dom


def fetch_json(url, warm=True):
    body = fetch(url)
    if body is None and warm:
        fetch(f"{BASE}/home", budget=15000)                     # earn bot-manager cookie
        body = fetch(url)
    if body is None:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def filings():
    j = fetch_json(f"{BASE}/nbm/map/api/published/filing")
    if not j:
        return []
    rows = j.get("data", [])
    def key(r):
        s = r["filing_subtype"]
        mo, _, yr = s.replace(",", "").split()
        return (int(yr), 12 if mo == "December" else 6)
    return sorted(rows, key=key)


def mobile_detail(uuid, lat, lon):
    j = fetch_json(f"{BASE}/nbm/map/api/mobile/detail/{uuid}/{lat}/{lon}")
    return j.get("data", []) if j else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--version", default="latest",
                    help='"latest", "all", or a subtype like "December 31, 2024"')
    ap.add_argument("--csv")
    a = ap.parse_args()

    fl = filings()
    if not fl:
        sys.exit("Could not reach the FCC API (blocked or offline). Retry in a few minutes.")

    print(f"Published vintages available: {len(fl)}")
    for f in fl:
        print(f"   {f['filing_subtype']:<22} process_uuid={f['process_uuid']}")
    print()

    if a.version == "all":
        targets = fl
    elif a.version == "latest":
        targets = fl[-1:]
    else:
        targets = [f for f in fl if f["filing_subtype"].lower() == a.version.lower()]
        if not targets:
            sys.exit(f"No such vintage. Choose from: {[f['filing_subtype'] for f in fl]}")

    out = []
    for f in targets:
        rows = mobile_detail(f["process_uuid"], a.lat, a.lon)
        print(f"=== {f['filing_subtype']}  @ {a.lat}, {a.lon}")
        if rows is None:
            print("    request blocked/rate-limited - try again shortly\n")
            continue
        if not rows:
            print("    no mobile coverage reported at this point\n")
            continue
        print(f"    {'Provider':<12} {'Tech':<8} {'Min Down':>8} {'Min Up':>7} "
              f"{'Min Signal':>11}  Holding Company")
        for r in rows:
            tech = r.get("technology_type") or TECH.get(r.get("technology"), r.get("technology"))
            print(f"    {r['brandname']:<12} {tech:<8} {r['mindown']:>8} {r['minup']:>7} "
                  f"{str(r['minsignal'])+' dBm':>11}  {r['holding_company']}")
            out.append({"as_of": f["filing_subtype"], "lat": a.lat, "lon": a.lon,
                        "provider": r["brandname"], "provider_id": r["providerid"],
                        "frn": r["frn"], "holding_company": r["holding_company"],
                        "technology": tech, "min_down_mbps": r["mindown"],
                        "min_up_mbps": r["minup"], "min_signal_dbm": r["minsignal"],
                        "environment": r["environmnt"]})
        print()

    if a.csv and out:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(out[0]))
            w.writeheader(); w.writerows(out)
        print(f"wrote {a.csv} ({len(out)} rows)")


if __name__ == "__main__":
    main()
