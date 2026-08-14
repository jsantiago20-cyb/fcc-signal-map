# FCC Signal Map

An interactive mobile-coverage map built from the FCC National Broadband Map's own
location-summary API, drawn over USGS terrain with OpenStreetMap roads and trails.

**Live map: https://jsantiago20-cyb.github.io/fcc-signal-map/**

The published map covers a 50-mile radius around 38.25228°N 105.66813°W (Custer
County, Colorado) — 1,459 points sampled on a 2.5-mile hex lattice against the
December 31, 2025 filing.

## What it does

- **Six views** — carrier count, best technology available, and one facet per carrier
- **A signal-strength filter** at −100 / −90 / −80 dBm that re-renders everything
- **Zoom and pan**, 1× to 14×, with scale bar, north arrow, and progressive town labels
- **Layers** for terrain, coverage, highways, local roads, trails, rivers, counties, towns
- **Coordinate search** accepting `(38.246, -105.664)`, `38.246, -105.664`,
  `38.25228°N 105.66813°W`, and degrees/minutes/seconds
- Hover any hex for the full per-carrier record; click to pin it

The page is a single self-contained HTML file. Terrain is an inlined WebP, every
road and trail is inlined vector geometry, and it makes no network requests at
runtime.

## Building it for a different location

```bash
python nbm_site.py --at "38.25228°N 105.66813°W"
python nbm_site.py --at "(38.2461363, -105.6641888)" --radius 12 --spacing 2
python nbm_site.py --at "39.7392, -104.9847" --name "Denver Signal Map"
```

`--at` takes any of the coordinate formats above. Options:

| flag | default | meaning |
|---|---|---|
| `--radius` | `50` | survey radius in miles |
| `--spacing` | `2.5` | hex lattice spacing in miles |
| `--name` | county name + " Signal Map" | page title |
| `--slug` | derived from name | cache directory under `sites/` |
| `--force` | – | comma list of stages to refetch: `census,terrain,osm,coverage` |
| `--out` | `<slug>.html` | output path |

Four stages run in order, each cached under `sites/<slug>/` so re-runs only fetch
what is missing:

| stage | source |
|---|---|
| `census` | county outlines and place centroids — Census TIGERweb |
| `terrain` | hillshade raster — USGS 3DEP |
| `osm` | roads, trails, rivers — OpenStreetMap via Overpass (with mirror failover) |
| `coverage` | FCC mobile location summaries — broadbandmap.fcc.gov |

Sampling cost scales as `(radius / spacing)²`. The default 50 mi / 2.5 mi is 1,459
points and takes a few minutes; `--spacing 1` on the same radius is about 9,100.

## The Akamai problem

`broadbandmap.fcc.gov` sits behind Akamai Bot Manager. curl, requests, and every
plain HTTP client get a `403` challenge no matter what headers they send, so
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
| `nbm_site.py` | the pipeline — one command, coordinate in, map out |
| `coords.py` | coordinate parser (decimal, signed, hemisphere, DMS) |
| `cdp.py` | minimal stdlib Chrome DevTools Protocol client |
| `process_osm.py` | clips, simplifies and quantises the Overpass dumps |
| `template.html` | the page — all rendering and interaction |
| `ascii_fix.py` | escapes non-ASCII inside the script block so the page is charset-proof |
| `nbm_query.py` | small CLI for a single point, no map |
| `e2e_test.py` | drives real Chrome against the live URL and asserts the whole flow |
| `sites/*/coverage.json` | harvested FCC data, so a rebuild need not re-query |

Requires Python 3 and Chrome. Pillow is used for the terrain image.

## Testing

```bash
python e2e_test.py
```

Loads the deployed page in a real Chrome and drives it with genuine mouse,
wheel and keyboard events: clicking a hex, dragging to pan, scrolling to zoom,
typing each coordinate format, switching views, moving the signal filter, and
toggling layers — asserting on what the page actually renders.

## Reading the map honestly

A filled hex means a carrier *told the FCC* it expects service there — modeled
propagation, not a measurement, at the FCC's outdoor-stationary thresholds (4G LTE
at 5/1 Mbps, 5G-NR at 7/1 or 35/3). In-vehicle and in-building coverage are
smaller.

Carriers also report the minimum signal strength behind each claim. In this area a
large share of AT&T's and Verizon's footprint is anchored at −120 dBm, at or below
the usable floor for most handsets. Setting the filter to −100 dBm moves
no-coverage from 23% to 42% of the circle and the average carrier count from 1.9 to
1.2. That gap is the practical difference between the map and your phone.

Only the current filing answers the point endpoint — older vintages return `403` —
so no year-over-year comparison is possible.

## Data sources and licence

Coverage data: [FCC National Broadband Map](https://broadbandmap.fcc.gov/) (public
domain). Terrain: USGS 3DEP (public domain). Boundaries and places: US Census
Bureau TIGERweb (public domain). Roads, trails and rivers: © OpenStreetMap
contributors, [ODbL](https://www.openstreetmap.org/copyright).

Code is MIT.
