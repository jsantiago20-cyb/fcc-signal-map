# The builder

A Cloudflare Worker that starts survey harvests for the map page.

The page is static, so it cannot hold a GitHub token without handing one to
every visitor. This Worker holds it instead. The page POSTs a coordinate, the
Worker validates it and starts the `Build a survey` workflow. Nobody signs in,
and no credential ever reaches a browser.

```
POST /build   {lat, lon, radius?, spacing?}   ->  {ok: true, queued: 1}
GET  /status                                  ->  {run: {status, conclusion, ...}}
```

It refuses coordinates outside the United States, radii outside 5 to 100 miles,
spacings outside 1 to 10 miles, anything over 3,000 sample points, and any
request that arrives while three harvests are already running. Cross-origin
requests are allowed only from the map page's own origin.

## Setting it up

One free Cloudflare account and one GitHub token, once:

```bash
cd builder
npx wrangler login                 # opens a browser, approve the request
npx wrangler secret put GH_TOKEN   # paste the token, it is never echoed
npx wrangler deploy
```

The token is a fine-grained personal access token for
`jsantiago20-cyb/fcc-signal-map`, with **Actions: read and write**. Make it at
https://github.com/settings/personal-access-tokens/new. Nothing else needs it,
so scope it to that one repository.

`wrangler deploy` prints the Worker's URL. Put that URL in `app_body.html` as
`BUILDER`, run `python build_app.py`, and push. The page uses the builder when
it is set, falls back to a token saved in the browser if not, and falls back
again to a prefilled GitHub issue.

## When the token expires

The page will say the builder's token was rejected. Make a new one and run
`npx wrangler secret put GH_TOKEN` again; nothing else changes.
