# Deploying runcalendar.com (static site, DigitalOcean App Platform)

This repository is the complete runcalendar.com website — plain HTML/CSS,
**no build step, no Node, no server code**. Every file is served exactly as-is.

## What to do (about 5 minutes)

### Option A — add to the existing DigitalOcean app (recommended)

1. DigitalOcean → **Apps** → open the app that currently serves runcalendar.com.
2. **Create → Create Resource From Source Code** (or Settings → Components →
   **Add Component**) → **Static Site**.
3. Connect GitHub and pick **this repository**, branch **main**.
   - Source directory: `/`
   - Build command: **none / leave empty**
   - Output directory: `/`
4. In the static site's settings, set **Custom Pages → Catchall page**
   to `404.html`.
5. Routing: make sure the static site serves the root path `/` of
   runcalendar.com (move the route off the old Next.js service).
6. Once the static site is live on the domain, **delete the old Next.js
   web-service component** — it's fully replaced (this also drops its
   monthly cost; static sites are free/cheap on App Platform).

### Option B — fresh app (if you'd rather not touch the old one)

1. **Apps → Create App** → GitHub → this repository, branch `main` →
   it will auto-detect a static site. Same settings as above (no build
   command, output `/`, catchall `404.html`).
2. Move the runcalendar.com domain: remove it from the old app
   (Settings → Domains), add it to the new app. DNS records don't change
   if the domain already points at DigitalOcean.
3. Delete the old app when the new one is serving.

## Things that must keep working (they do, automatically)

- **`runcalendar.com/claim?event=<id>`** — the app links this with a query
  string; static hosting serves `/claim/index.html` and the page's own
  JavaScript reads the query string. Nothing to configure.
- **`runcalendar.com/privacy`** — referenced by App Store metadata.
- Leave **auto-deploy on push** enabled: future site updates arrive by
  Rochelle pushing to this repository — no DigitalOcean work needed again.

## Contact

Any questions: rochelle@evento.co.nz — the site was built and verified
11 Aug 2026; every page and asset returns 200 and the forms are live-wired
to the existing Supabase backend (no configuration needed on the DO side).

## The catalogue (added 12 Oct 2026)

`/races/…` (world → country → region → month hubs) and `/race/<slug>/` (one page per
upcoming race, ~15,000) are **generated**, never hand-edited:

- Generators live in the app repo at `Tools/website/` and are copied into this
  repository's `tools/` on every sync. `build_collections.py` runs first, then
  `build_catalogue.py --out .` (it owns `/race/`, `sitemap.xml` and the
  `sitemap-*.xml` chunks, `/races/<cc>/search.json` and `_catalogue.css`).
- **Nightly rebuild**: `.github/workflows/nightly.yml` runs both generators at
  14:30 UTC, commits whatever changed and pushes — DigitalOcean deploys as it
  does for a hand push. No secrets: it reads the public API only.
- **Satellite frames** come from the public `web-assets` bucket
  (`sat/<event_id>.jpg`, a 1280×800 progressive JPEG re-encoded from Apple's
  1.8 MB PNG, + `sat/manifest.json`, a JSON list of the event ids held), written by
  `Tools/website/fetch_snapshots.py` run on Rochelle's Mac with the Apple Maps
  key and the Supabase service key in `~/Documents/RunCalendarSecrets/maps.env`
  (never in any repo). New races get the brand gradient until the next frame run
  — run it after the morning list once a week or so.
- The app repo does NOT track the generated pages (`website/races/`,
  `website/race/`, `website/sitemap*.xml`, `website/_catalogue.css` are
  git-ignored there). Hand-made pages still flow app repo → here by rsync;
  never rsync with `--delete` across the generated directories.
- Design reference: `Design/web_catalogue_mock` in the app repo (owner-approved
  12 Oct 2026): satellite hero + grey box on every hub, two-column calendar,
  race page = the app's Event Detail with the organiser link last.
