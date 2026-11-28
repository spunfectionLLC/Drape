# The website (spunfection.studio)

The whole studio runs in the visitor's browser. Nothing is computed on a server, and
nothing the visitor types or designs leaves their computer.

| Part | Where it runs |
|---|---|
| The studio page and its scripts | the browser (the same files as the desktop app) |
| Avatars, drafting, fit checks, exports | Python in the browser: Pyodide in a Web Worker (`web/site/py_worker.js`), running drape's code from `drape_bundle.zip` |
| Drape it | the graphics card, through WebGPU (`live_springs.js`, the live mode solver) |
| The studio's `/api/...` calls | answered in the page by `web/site/web_shim.js` → `drape/webapi.py` |

Pyodide and its packages (numpy, SciPy, Shapely, matplotlib, scikit-image, ezdxf) come from
the jsDelivr CDN: about 40–60 MB on the first visit, then the browser caches them.

## Build and try it locally

    python tools/build_site.py
    python -m http.server -d out/site 8000      # then open http://localhost:8000

WebGPU needs https or localhost, so test on `localhost`, not the computer's IP address.

## Deploy to Cloudflare

The site is a Cloudflare Worker that only serves static files (`wrangler.jsonc`: the
files in `out/site/`). Wrangler signs in with an API token from the environment, never
with `wrangler login`.

One-time setup:
1. In the Cloudflare dashboard: My Profile → API Tokens → Create Token → the
   "Edit Cloudflare Workers" template, for account 759f8c8b69c9f5600bf45ab18d41775e.
2. Save it as Windows user environment variables (not in any file in the repo):
   `CLOUDFLARE_API_TOKEN` (the token) and `CLOUDFLARE_ACCOUNT_ID` (759f8c8b69c9f5600bf45ab18d41775e).
   Close and reopen terminals and VS Code afterwards so they see them.

Each release:

    python tools/build_site.py
    npx wrangler deploy --dry-run --outdir %TEMP%\wrangler_dry
    npx wrangler deploy

Live at https://spunfection.studio and https://www.spunfection.studio (Custom Domains in
`wrangler.jsonc`: Cloudflare manages their DNS records and certificates). The workers.dev
address is off. Earlier versions: the Worker's Deployments tab in the dashboard.
The first live version: d1f85bac-6ff2-4855-a42f-3fe3847eb01d (2026-11-22).
Zone setting **Always Use HTTPS: on** (2026-11-22): http redirects to https, which WebGPU needs
(on plain http the page loads but Drape it can't run). HSTS is off for now.

## What the web version doesn't have yet
- Move tests (sitting, walking…): they need the moving body on the GPU. The page says so.
- Drape it on a browser without WebGPU (Firefox before WebGPU, older Safari): the studio
  still designs and exports; the drape says it needs Chrome or Edge 113+ or Safari 26+.
- The drape doesn't weld seams while it runs (the welds happen at the end, before the fit
  check). Rarely a seam corner can catch (the trouser hem, see the `gpu-drape` branch).

## Before the public launch
- Terms and Privacy are placeholder pages ("Coming before public launch") in `drape/brand.py`.
- Source code and Report a bug point to placeholder pages until the public repo exists.
