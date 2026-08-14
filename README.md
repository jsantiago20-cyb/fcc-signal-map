# Cellular Signal Map

An interactive map of reported US mobile coverage, built from the FCC National
Broadband Map's own location-summary API and drawn over USGS terrain with
OpenStreetMap roads and trails.

**Live: https://jsantiago20-cyb.github.io/fcc-signal-map/**

Type any coordinate in the United States. If a survey already covers it, the map
opens on that point with the full carrier breakdown. If not, the page says so and
gives you a one-click way to build one.

Published surveys:

| area | centre | radius | carriers |
|---|---|---|---|
| Custer County, CO | 38.25228N 105.66813W | 50 mi | AT&T, T-Mobile, Verizon, Viaero |
| Denver County, CO | 39.73920N 104.98470W | 50 mi | T-Mobile, AT&T, Verizon, Viaero, Union Telephone |

The carrier list is derived per survey, so a new area picks up whatever regional
operators file there.

## What it does

- **Any US coordinate** — decimal, signed, parenthesised, hemisphere letters, or
  degrees/minutes/seconds. `(38.246, -105.664)`, `38.25228°N 105.66813°W` and
  `N38 15 8.2 W105 40 5.3` all parse to the same place.
- **Six views** — carrier count, best technology available, and one per carrier
- **A signal-strength filter** at −100 / −90 / −80 dBm that re-renders everything
- **Zoom and pan**, 1× to 14×, with scale bar, north arrow and progressive town labels
- **Layers** for terrain, coverage, highways, local roads, trails, rivers, counties, towns
- Hover a hex for the full per-carrier record; click to pin it
- Deep-links: `?at=38.25228,-105.66813` opens straight on a point

## Why surveys are pre-built

`broadbandmap.fcc.gov` sits behind Akamai Bot Manager and returns `403` to any
request from another website. That is not a CORS problem you can proxy around —
the origin refuses the request outright. Of the four upstreams this map uses, it
is the only one that does:

| source | reachable from a web page? |
|---|---|
| USGS 3DEP (terrain) | yes — `Access-Control-Allow-Origin: *` |
| Census TIGERweb (boundaries, places) | yes — echoes the origin |
| `geo.fcc.gov` (geocoding) | yes — `*` |
| **`broadbandmap.fcc.gov` (coverage)** | **no — 403** |

So coverage has to be harvested by a real browser, ahead of time, and shipped as
static data. A **survey** is one such harvest: a circle of sample points around a
centre. The site loads whichever survey contains your coordinate.

## Building a survey

**On GitHub Actions** — no local setup. Open
[Actions → Build a survey](../../actions/workflows/build-survey.yml), click *Run
workflow*, and give it a coordinate. It harvests, commits the pack, and the site
redeploys with the new area in the list.

**Locally:**

```bash
pip install pillow
python nbm_site.py --at "38.25228°N 105.66813°W"
python nbm_site.py --at "(38.2461363, -105.6641888)" --radius 12 --spacing 2
python nbm_site.py --at "39.7392, -104.9847" --name "Denver metro"
```

| flag | default | meaning |
|---|---|---|
| `--radius` | `50` | survey radius in miles |
| `--spacing` | `2.5` | hex lattice spacing in miles |
| `--name` | county, state | label shown in the survey list |
| `--slug` | derived from name | cache and pack directory name |
| `--force` | – | stages to refetch: `census,terrain,osm,coverage` |

Four stages run in order, each cached under `sites/<slug>/` so re-runs only fetch
what is missing:

| stage | source |
|---|---|
| `census` | county outlines and place centroids — Census TIGERweb |
| `terrain` | hillshade raster — USGS 3DEP |
| `osm` | roads, trails, rivers — OpenStreetMap via Overpass (mirror failover) |
| `coverage` | FCC mobile location summaries — broadbandmap.fcc.gov |

Output is a **pack**: `surveys/<slug>/data.json` plus `terrain.webp`, with an
entry appended to `surveys.json`. The page shell is 49 KB and pulls a pack only
when you ask for that area.

Sampling cost scales as `(radius / spacing)²`. The default 50 mi / 2.5 mi is 1,459
points and takes a few minutes; `--spacing 1` on the same radius is about 9,100.

## The Akamai problem, in detail

`cdp.py` is a dependency-free Chrome DevTools Protocol client — WebSocket
handshake and framing written against the standard library — that drives a real
headless Chrome and issues the fetches *from inside a broadbandmap.fcc.gov page*.
Same origin, real cookies, no CORS.

The edge also flags a session after roughly 1,300 requests, and once flagged that
session returns `403` forever — but a **fresh browser profile gets a clean session
immediately**. The harvester detects a burned session (a whole chunk returning
nothing) and rotates to a new profile, which is why long runs complete.

Requests are issued four at a time. Please keep it that way.

## Files

| file | what it is |
|---|---|
| `nbm_site.py` | the pipeline — coordinate in, survey pack out |
| `coords.py` | coordinate parser (decimal, signed, hemisphere, DMS) |
| `cdp.py` | minimal stdlib Chrome DevTools Protocol client |
| `process_osm.py` | clips, simplifies and quantises the Overpass dumps |
| `app_head.html`, `app_body.html` | the page; `build_app.py` joins them into `index.html` |
| `build_app.py` | concatenates the shell and escapes non-ASCII in the script |
| `e2e_test.py` | drives real Chrome against the live URL and asserts the whole flow |
| `nbm_query.py` | small CLI for a single point, no map |
| `surveys.json` | index of published surveys |
| `surveys/<slug>/` | a published pack: `data.json` + `terrain.webp` |
| `sites/<slug>/` | local fetch cache, so rebuilds do not re-query anyone |

Edit `app_body.html`, not `index.html` — `index.html` is generated.

Requires Python 3 and Chrome. Pillow is used for the terrain image.

## Testing

```bash
python e2e_test.py
```

Loads the deployed page in a real Chrome and drives it with genuine mouse, wheel
and keyboard events: clicking a hex, dragging to pan, scrolling to zoom, typing
each coordinate format, switching views, moving the signal filter, and toggling
layers — asserting on what the page actually renders.

## Reading the map honestly

A filled hex means a carrier *told the FCC* it expects service there — modeled
propagation, not a measurement, at the FCC's outdoor-stationary thresholds (4G LTE
at 5/1 Mbps, 5G-NR at 7/1 or 35/3). In-vehicle and in-building coverage are
smaller.

Carriers also report the minimum signal strength behind each claim. Around Custer
County a large share of AT&T's and Verizon's footprint is anchored at −120 dBm, at
or below the usable floor for most handsets. Setting the filter to −100 dBm moves
no-coverage from 24% to 41% of that circle and the average carrier count from 1.9
to 1.2. That gap is the practical difference between the map and your phone.

Each hex is one point sample, not a polygon the FCC published, so edges are
accurate to about the survey's spacing. Only the current filing answers the point
endpoint — older vintages return `403` — so no year-over-year comparison is
possible.

## Data sources and licence

Coverage: [FCC National Broadband Map](https://broadbandmap.fcc.gov/) (public
domain). Terrain: USGS 3DEP (public domain). Boundaries and places: US Census
Bureau TIGERweb (public domain). Roads, trails and rivers: © OpenStreetMap
contributors, [ODbL](https://www.openstreetmap.org/copyright).

Code is MIT.
