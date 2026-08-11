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
