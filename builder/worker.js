/**
 * fcc-signal-map builder - a Cloudflare Worker that starts survey harvests.
 *
 * The map page is static, so it cannot hold a GitHub token without handing one
 * to every visitor. This Worker holds it instead: the page POSTs a coordinate,
 * the Worker checks it and starts the repository's "Build a survey" workflow.
 * Nobody signs in, nothing is stored in a browser.
 *
 *   POST /build   {lat, lon, radius?, spacing?}  ->  {ok, queued}
 *   GET  /status                                 ->  {run: {...}}
 *
 * Set the secret once:  npx wrangler secret put GH_TOKEN
 * A fine-grained token for this repository with Actions: read and write.
 */

const REPO = "jsantiago20-cyb/fcc-signal-map";
const WORKFLOW = "build-survey.yml";
const ORIGINS = ["https://jsantiago20-cyb.github.io", "http://localhost:8765"];

const RADIUS = [5, 100];          // miles
const SPACING = [1, 10];          // miles between samples
const MAX_POINTS = 3000;          // about 3.6 * (radius / spacing) ** 2
const MAX_QUEUED = 3;             // runs waiting before the builder says no

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": ORIGINS.indexOf(origin) >= 0 ? origin : ORIGINS[0],
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function reply(body, status, cors) {
  return new Response(JSON.stringify(body), {
    status: status,
    headers: Object.assign({ "Content-Type": "application/json" }, cors),
  });
}

function gh(path, env, init) {
  const opts = Object.assign({}, init);
  opts.headers = Object.assign({
    "Accept": "application/vnd.github+json",
    "Authorization": "Bearer " + env.GH_TOKEN,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "fcc-signal-map-builder",
  }, init && init.headers);
  return fetch("https://api.github.com/repos/" + REPO + path, opts);
}

function number(v, fallback, range, label) {
  if (v === undefined || v === null || v === "") return [fallback, ""];
  const n = Number(v);
  if (!isFinite(n)) return [null, label + " is not a number"];
  if (n < range[0] || n > range[1]) {
    return [null, label + " has to be between " + range[0] + " and " + range[1]];
  }
  return [n, ""];
}

async function build(req, env, cors) {
  if (!env.GH_TOKEN) {
    return reply({ error: "the builder has no GitHub token configured" }, 500, cors);
  }

  let body;
  try { body = await req.json(); }
  catch (e) { return reply({ error: "send JSON" }, 400, cors); }

  const lat = Number(body.lat), lon = Number(body.lon);
  if (!isFinite(lat) || !isFinite(lon)) {
    return reply({ error: "lat and lon are required" }, 400, cors);
  }
  if (!(lat >= 17.5 && lat <= 72 && lon >= -180 && lon <= -64)) {
    return reply({ error: "that coordinate is outside the United States, "
                        + "so the FCC has no data for it" }, 400, cors);
  }

  const [radius, rErr] = number(body.radius, 50, RADIUS, "radius");
  if (rErr) return reply({ error: rErr }, 400, cors);
  const [spacing, sErr] = number(body.spacing, 2.5, SPACING, "spacing");
  if (sErr) return reply({ error: sErr }, 400, cors);

  const points = 3.6 * Math.pow(radius / spacing, 2);
  if (points > MAX_POINTS) {
    return reply({ error: "that radius and spacing come to about " + Math.round(points)
                        + " sample points, over the " + MAX_POINTS + " cap" }, 400, cors);
  }

  // One harvest at a time is the design; a short queue behind it is fine, a
  // flood is not. The workflow's own concurrency group does the serialising.
  let queued = 0;
  try {
    const r = await gh("/actions/workflows/" + WORKFLOW + "/runs?per_page=10", env);
    if (r.ok) {
      const j = await r.json();
      queued = (j.workflow_runs || []).filter(x => x.status !== "completed").length;
    }
  } catch (e) { /* if GitHub will not say, let the dispatch decide */ }
  if (queued >= MAX_QUEUED) {
    return reply({ error: "the builder already has " + queued + " harvests running. "
                        + "Try again in a few minutes." }, 429, cors);
  }

  const at = lat.toFixed(6) + ", " + lon.toFixed(6);
  const res = await gh("/actions/workflows/" + WORKFLOW + "/dispatches", env, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: {
      at: at, radius: String(radius), spacing: String(spacing) } }),
  });

  if (res.status === 204) return reply({ ok: true, at: at, queued: queued + 1 }, 200, cors);

  let detail = "";
  try { detail = (await res.json()).message || ""; } catch (e) {}
  if (res.status === 401) detail = "the builder's GitHub token was rejected; it may have expired";
  if (res.status === 403) detail = "the builder's GitHub token cannot start workflow runs";
  if (res.status === 404) detail = "the builder's GitHub token cannot see the repository";
  return reply({ error: detail || ("GitHub returned " + res.status) }, 502, cors);
}

async function status(env, cors) {
  if (!env.GH_TOKEN) return reply({ run: null }, 200, cors);
  const r = await gh("/actions/workflows/" + WORKFLOW + "/runs?per_page=1", env);
  if (!r.ok) return reply({ run: null }, 200, cors);
  const run = ((await r.json()).workflow_runs || [])[0] || null;
  return reply({ run: run && {
    status: run.status, conclusion: run.conclusion,
    html_url: run.html_url, run_started_at: run.run_started_at } }, 200, cors);
}

export default {
  async fetch(req, env) {
    const cors = corsHeaders(req.headers.get("Origin") || "");
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const path = new URL(req.url).pathname.replace(/\/+$/, "") || "/";
    if (path === "/build" && req.method === "POST") return build(req, env, cors);
    if (path === "/status") return status(env, cors);
    if (path === "/") {
      return reply({ builder: REPO, endpoints: ["POST /build", "GET /status"] }, 200, cors);
    }
    return reply({ error: "no such endpoint" }, 404, cors);
  },
};
