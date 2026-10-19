#!/usr/bin/env python3
"""Generate runcalendar.com/collections/… and /race/… from the live catalogue.

Run from the repo root:  python3 Tools/website/build_collections.py
Writes into website/ (the source of truth); sync to the deploy clone after.
Reads Supabase over the public anon REST endpoint — published rows only.
"""
import json, re, html, datetime, os, sys, urllib.request, urllib.parse, collections

REST = "https://rteqvslwxgsgvccrgtzg.supabase.co/rest/v1"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ0ZXF2c2x3eGdzZ3ZjY3JndHpnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2NDExOTUsImV4cCI6MjA1OTIxNzE5NX0.9nS2ATC2p2bfruWNhKylrIPamtYfnb6hTSyv5GC5Ksw"
SITE = "https://runcalendar.com"
STORE = "https://apps.apple.com/app/apple-store/id6726998429?pt=2876806&mt=8&ct="
ROOT = os.environ.get("SITE_ROOT") or os.path.join(os.path.dirname(__file__), "..", "..", "website")
TODAY = datetime.date.today()
TAGLINE = "Your next race, seen from above."

CC = {"US": ("us", "United States", "the United States", "en-US"), "AU": ("au", "Australia", "Australia", "en-AU"),
      "ZA": ("za", "South Africa", "South Africa", "en-ZA"), "GB": ("uk", "United Kingdom", "the UK", "en-GB"),
      "CA": ("ca", "Canada", "Canada", "en-CA"), "IE": ("ie", "Ireland", "Ireland", "en-IE"),
      "NZ": ("nz", "New Zealand", "New Zealand", "en-NZ")}  # owner order 2026-09-17: the download markets
HOME_EXCLUDE = {"great-10ks"}
MOOD_ORDER = ["world-marathon-majors", "flat-friendly", "chasing-a-pb", "pink-runs", "american-fall-classics",
              "beach-coast", "trail-escapes", "worth-the-flight", "big-city-halves", "great-10ks", "trails-worth-the-trip",
              "winter-sun", "run-europe", "race-guides"]  # globals = owner's tile order 2026-09-20 (db-requests 149e)

def get(path):
    req = urllib.request.Request(REST + path, headers={"apikey": ANON, "Authorization": "Bearer " + ANON})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def esc(s): return html.escape(s or "", quote=True)

def when(d, confirmed):
    dt = datetime.date.fromisoformat(d)
    return (dt.strftime("%-d"), dt.strftime("%b"), dt.strftime("%Y")) if confirmed else ("", dt.strftime("%b"), dt.strftime("%Y"))

NAMES = {"42.2": "Marathon", "42.195": "Marathon", "21.1": "Half marathon", "21.0975": "Half marathon", "10": "10K", "5": "5K",
         "16.1": "10 miles", "8": "5 miles", "8.0": "5 miles", "8.1": "5 miles", "12": "12K", "15": "15K", "50": "50K", "80.5": "50 miles", "160.9": "100 miles", "161": "100 miles", "100": "100K"}
def distances(summary):
    if not summary: return ""
    s = summary.strip()
    m = re.match(r"^(.*?)\s*(k|km|mi)$", s)
    unit = "km"
    if m: s, unit = m.group(1), ("mi" if m.group(2) == "mi" else "km")
    parts = [p.strip() for p in re.split(r"\s*/\s*", s)]
    out = []
    for p in parts:
        if unit == "km" and p in NAMES: out.append(NAMES[p])
        else: out.append(p + (" km" if unit == "km" else " mi"))
    return " · ".join(out)

def mood_of(c):
    slug = c["slug"]; countries = c.get("countries")
    if not countries: return None, slug
    iso = countries[0]
    suffix = "-" + iso.lower()
    mood = slug[:-len(suffix)] if slug.endswith(suffix) else slug
    return iso, mood

def page_path(c):
    iso, mood = mood_of(c)
    return f"/collections/{CC[iso][0]}/{mood}/" if iso else f"/collections/{mood}/"

def head(title, desc, canonical, lang="en", extra="", noindex=False, ld=None, og_image=None):
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE}{canonical}">
{'<meta name="robots" content="noindex,follow">' if noindex else ''}
<link rel="icon" href="/assets/appicon-64.png" type="image/png">
<link rel="apple-touch-icon" href="/assets/appicon-180.png">
<meta property="og:type" content="website">
<meta property="og:site_name" content="RunCalendar">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{SITE}{canonical}">
<meta property="og:image" content="{esc(og_image or SITE + '/assets/og.jpg')}">
<link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:ital,wght@0,400..900;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/_shared.css">
{('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + '</script>') if ld else ''}
<style>{extra}</style>
</head>
<body>
<nav><div class="wrap navin">
  <a class="brand" href="/"><span class="mark"></span>RunCalendar</a>
  <div class="navlinks"><a href="/races/">Races</a><a href="/collections/">Collections</a><a href="/about/">About</a><a href="/add-event/">Add your event</a><a class="navcta" href="/#download">Get the app</a></div>
</div></nav>
"""

FOOT = """<footer><div class="wrap fin">
  <div>© 2026 RunCalendar · Net Project Limited</div>
  <div class="flinks"><a href="/races/">Races</a><a href="/collections/">Collections</a><a href="/about/">About</a><a href="/contact/">Contact</a><a href="/add-event/">Add your event</a><a href="/privacy/">Privacy</a><a href="/terms/">Terms</a></div>
</div></footer>
</body></html>
"""

CSS_COLLECTION = """
.crumbs{font-size:13px;font-weight:600;color:var(--muted);padding-top:22px;max-width:760px;margin:0 auto}
.crumbs a{color:var(--secondary);text-decoration:none}.crumbs span{margin:0 6px;color:var(--hairline)}
.pagehead{padding-top:22px}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--greenDeep);margin-bottom:12px}
.hero{max-width:760px;margin:26px auto 0;aspect-ratio:16/9;border-radius:16px;overflow:hidden;background:var(--surface)}
.hero img{width:100%;height:100%;object-fit:cover;display:block}
.count{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:34px 0 4px}
ul.races{list-style:none}
.race{display:grid;grid-template-columns:64px 1fr auto;gap:18px;align-items:start;padding:20px 0;border-top:1px solid var(--hairline)}
.race:first-child{border-top:0}
.d{text-align:center;line-height:1.05;padding-top:2px}
.d b{display:block;font-size:26px;font-weight:800;letter-spacing:-.02em;color:var(--ink)}
.d span{display:block;font-size:12.5px;font-weight:700;color:var(--secondary);margin-top:3px}
.d .y{font-size:11px;font-weight:600;color:var(--muted)}
.d.prov b{font-size:18px;padding-top:6px}
.race h3{font-size:18px;font-weight:800;letter-spacing:-.015em;line-height:1.2}
.race h3 a{color:inherit;text-decoration:none}.race h3 a:hover{color:var(--greenDeep)}
.meta{font-size:13.5px;font-weight:600;color:var(--secondary);margin-top:4px}
.hook{font-size:14.5px;line-height:1.55;color:var(--greenDeep);font-style:italic;margin-top:6px!important}
.acts{padding-top:2px}
.save{background:var(--green);color:#fff;font-weight:700;font-size:13px;padding:9px 14px;border-radius:99px;text-decoration:none;white-space:nowrap;display:inline-block}
.save:hover{background:var(--greenDeep)}
.more{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.more a{font-size:13.5px;font-weight:700;color:var(--greenDeep);background:var(--greenTint);padding:8px 13px;border-radius:99px;text-decoration:none}
.dl{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.dl .btn{background:var(--ink);color:#fff;font-weight:700;padding:11px 18px;border-radius:99px;text-decoration:none;font-size:14px;white-space:nowrap}
.fine{font-size:12.5px;color:var(--muted);margin-top:22px!important}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-top:14px}
.ccard{border:1px solid var(--hairline);border-radius:16px;overflow:hidden;text-decoration:none;color:inherit;background:#fff;display:block}
.ccard .ph{aspect-ratio:16/9;background:var(--surface)}.ccard .ph img{width:100%;height:100%;object-fit:cover;display:block}
.ccard .cb{padding:12px 14px 14px}.ccard h3{font-size:16px;font-weight:800;letter-spacing:-.01em}
.ccard .cs{font-size:13px;color:var(--secondary);margin-top:3px}.ccard .cn{font-size:12px;font-weight:700;color:var(--greenDeep);margin-top:8px}
.content.wide{max-width:1120px}
@media(max-width:720px){.race{grid-template-columns:52px 1fr}.acts{grid-column:2}.d b{font-size:22px}}
"""

def write(path, content):
    full = os.path.join(ROOT, path.strip("/"), "index.html") if path.endswith("/") else os.path.join(ROOT, path.strip("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    open(full, "w").write(content)

def race_href(e, from_token): return f"/race/{e['slug']}/?from={from_token}"

def collection_page(c, evs, siblings, all_by_slug):
    iso, mood = mood_of(c)
    cc, cname, cin, lang = CC[iso] if iso else (None, None, None, "en")
    path = page_path(c); token = f"web-{cc}-{mood}" if iso else f"web-{mood}"
    title = f"{c['title']} — {c['subtitle']} | RunCalendar" if c.get("subtitle") else f"{c['title']} | RunCalendar"
    desc = (c.get("description") or c.get("subtitle") or c["title"])
    if len(desc) > 155: desc = desc[:152].rsplit(" ", 1)[0] + "…"
    rows = []
    for e in evs:
        day, mon, yr = when(e["next_event_date"], e["next_date_confirmed"])
        date_html = f'<div class="d"><b>{day}</b><span>{mon}</span><span class="y">{yr}</span></div>' if day else f'<div class="d prov"><b>{mon}</b><span class="y">{yr}</span></div>'
        place = esc(e["city_name"] or "")
        if e.get("state_code") and e["country"] in ("US", "AU", "CA"): place += ", " + esc(e["state_code"])
        elif e.get("state_name") and e["state_name"].lower() != (e["city_name"] or "").lower(): place += ", " + esc(e["state_name"])
        if not iso: place += ", " + esc(e["country_name"] or "")
        dist = distances(e.get("distance_summary"))
        hook = f'<p class="hook">{esc(e["hook"])}</p>' if e.get("hook") else ""
        href = race_href(e, token)
        rows.append(f'''<li class="race">
  {date_html}
  <div class="t"><h3><a href="{href}">{esc(e["name"])}</a></h3><div class="meta">{place}{(" · " + esc(dist)) if dist else ""}</div>{hook}</div>
  <div class="acts"><a class="save" href="{href}">Save in RunCalendar</a></div>
</li>''')
    crumbs = f'<a href="/collections/">Collections</a><span>›</span>' + (f'<a href="/collections/{cc}/">{esc(cname)}</a><span>›</span>' if iso else "") + esc(c["title"])
    ld = {"@context": "https://schema.org", "@type": "ItemList", "name": c["title"] + (f" — {c['subtitle']}" if c.get("subtitle") else ""),
          "url": SITE + path, "numberOfItems": len(evs),
          "itemListElement": [{"@type": "ListItem", "position": i + 1, "url": SITE + f"/race/{e['slug']}/", "item": {"@type": "SportsEvent", "name": e["name"], "startDate": e["next_event_date"], "sport": "Running",
                 "url": SITE + f"/race/{e['slug']}/",
                 "location": {"@type": "Place", "name": e["city_name"], "address": {"@type": "PostalAddress", "addressLocality": e["city_name"], "addressCountry": e["country"]}}}} for i, e in enumerate(evs)]}
    more = "".join(f'<a href="{page_path(s)}">{esc(s["title"])}</a>' for s in siblings if s["slug"] != c["slug"])
    heading = f"{esc(c['title'])}" if iso is None else f"{esc(c['title'])}"
    eyebrow = f"Collection · {esc(cname)}" if iso else "Collection · Worldwide"
    body = head(title, desc, path, lang, CSS_COLLECTION, ld=ld, og_image=c.get("hero_image_url")) + f"""
<div class="wrap">
  <div class="crumbs">{crumbs}</div>
  <div class="pagehead">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{heading}</h1>
    <p class="sub">{esc(c.get("subtitle") or "")}{". " if c.get("subtitle") and c.get("description") else ""}{esc(c.get("description") or "")}</p>
  </div>
  {f'<div class="hero"><img src="{esc(c["hero_image_url"])}" alt="{esc(c["title"])}"></div>' if c.get("hero_image_url") else ""}
</div>

<div class="content">
  <div class="count">{len(evs)} races · in date order</div>
  <ul class="races">
{chr(10).join(rows)}
  </ul>

  <h2>More collections{(" in " + esc(cin)) if iso else ""}</h2>
  <div class="more">{more}</div>

  <div class="tintcard dl">
    <div style="flex:1;min-width:240px"><b style="color:var(--greenDeep)">{TAGLINE}</b><br>Save any of these to your season in RunCalendar and hear the morning entries open. Free on the App Store.</div>
    <a class="btn" href="{STORE}{token}">Get RunCalendar</a>
  </div>

  <p class="fine">A confirmed date shows its day; a provisional one shows only its month, because we won't claim a day we don't have. This list is edited by RunCalendar and updated as the calendar moves. Last updated {TODAY.strftime("%-d %B %Y")}.</p>
</div>

""" + FOOT
    write(path, body)
    return path

def race_page(e, cols):
    day, mon, yr = when(e["next_event_date"], e["next_date_confirmed"])
    date_txt = f"{day} {mon} {yr}" if day else f"{mon} {yr}"
    place = e["city_name"] or ""
    if e.get("state_name") and e["state_name"].lower() != place.lower(): place += ", " + e["state_name"]
    place += ", " + (e["country_name"] or "")
    dist = distances(e.get("distance_summary"))
    title = f"{e['name']} — {date_txt} | RunCalendar"
    desc = (e.get("hook") or f"{e['name']} in {place}.") + " Save it to your season in RunCalendar."
    back = "".join(f'<a href="{page_path(c)}">{esc(c["title"])}</a>' for c in cols)
    body = head(title, desc, f"/race/{e['slug']}/", "en", CSS_COLLECTION + """
.racehead{max-width:760px;margin:0 auto;padding-top:40px}
.racehead .when{font-size:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--greenDeep)}
.racehead h1{font-size:40px;font-weight:800;letter-spacing:-.03em;line-height:1.08;margin-top:8px}
.racehead .place{font-size:16px;color:var(--secondary);font-weight:600;margin-top:8px}
.racehead .hook{font-size:17px;margin-top:14px!important}
.open{display:inline-block;background:var(--green);color:#fff;font-weight:800;font-size:16px;padding:14px 22px;border-radius:14px;text-decoration:none;margin-top:26px}
.open:hover{background:var(--greenDeep)}
.small{font-size:13px;color:var(--muted);margin-top:12px}
@media(max-width:720px){.racehead h1{font-size:30px}}
""", noindex=True) + f"""
<div class="wrap">
  <div class="crumbs"><a href="/collections/">Collections</a><span>›</span>{esc(e["name"])}</div>
  <div class="racehead">
    <div class="when">{esc(date_txt)}{(" · " + esc(dist)) if dist else ""}</div>
    <h1>{esc(e["name"])}</h1>
    <div class="place">{esc(place)}</div>
    {f'<p class="hook">{esc(e["hook"])}</p>' if e.get("hook") else ""}
    <a class="open" id="open" href="{STORE}web-race">Open in RunCalendar</a>
    <p class="small">Opens the race in the app if you have it, or the App Store if you don't. {TAGLINE}</p>
  </div>
</div>
<div class="content">
  <h2>In these collections</h2>
  <div class="more">{back}</div>
</div>
<script>
(function(){{
  var from = new URLSearchParams(location.search).get('from');
  var store = "{STORE}" + (from ? from : "web-race");
  var btn = document.getElementById('open'); btn.href = store;
  var deep = "runcalendar://event/{e['id']}";
  var ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
  if (ios) {{
    var f = document.createElement('iframe'); f.style.display = 'none'; f.src = deep; document.body.appendChild(f);
    setTimeout(function(){{ if (!document.hidden) location.replace(store); }}, 1500);
  }}
}})();
</script>
""" + FOOT
    write(f"/race/{e['slug']}/", body)

def card(c, n):
    ph = f'<div class="ph"><img loading="lazy" src="{esc(c["hero_image_url"])}" alt=""></div>' if c.get("hero_image_url") else '<div class="ph"></div>'
    return f'<a class="ccard" href="{page_path(c)}">{ph}<div class="cb"><h3>{esc(c["title"])}</h3><div class="cs">{esc(c.get("subtitle") or "")}</div><div class="cn">{n} races ›</div></div></a>'

def hub(cols, counts):
    globals_ = [c for c in cols if not c.get("countries")]
    by_iso = collections.defaultdict(list)
    for c in cols:
        if c.get("countries"): by_iso[c["countries"][0]].append(c)
    sections = "".join(f'<h2 id="{CC[iso][0]}">{esc(CC[iso][1])}</h2><div class="cards">{"".join(card(c, counts[c["id"]]) for c in by_iso[iso])}</div>' for iso in ["US", "AU", "ZA", "GB", "CA", "IE", "NZ"] if by_iso.get(iso))
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Race collections", "url": SITE + "/collections/"}
    body = head("Race collections — flat and fast, beach, trail, first races and more | RunCalendar",
                "Hand-edited lists of running races by country: flat and fast courses for a PB, beach and coast runs, trail escapes, friendly first finish lines, the pink runs, and the world's great races.",
                "/collections/", "en", CSS_COLLECTION, ld=ld) + f"""
<div class="wrap">
  <div class="pagehead" style="padding-top:56px">
    <div class="eyebrow">Collections</div>
    <h1>Races, <span class="g">sorted by the reason</span> you'd run them</h1>
    <p class="sub">Hand-edited lists from the RunCalendar calendar: the flat, fast courses for a personal best, the beach runs, the trail escapes, the friendliest first finish lines and the pink runs, one set per country, plus the races worth a flight.</p>
  </div>
</div>
<div class="content wide">
  <h2>Everywhere</h2><div class="cards">{"".join(card(c, counts[c["id"]]) for c in globals_)}</div>
  {sections}
  <div class="tintcard dl">
    <div style="flex:1;min-width:240px"><b style="color:var(--greenDeep)">{TAGLINE}</b><br>Every list here lives in the app, with the dates, the entry openings and a reminder the morning they open. Free on the App Store.</div>
    <a class="btn" href="{STORE}web-collections">Get RunCalendar</a>
  </div>
</div>
""" + FOOT
    write("/collections/", body)

def country_hub(iso, cols, counts):
    cc, cname, cin, lang = CC[iso]
    own = [c for c in cols if c.get("countries") and c["countries"][0] == iso]
    globals_ = [c for c in cols if not c.get("countries")]
    body = head(f"Running races in {cname} — collections | RunCalendar",
                f"Race collections for runners in {cin}: flat, fast courses for a PB, beach and coast runs, trail escapes, friendly first finish lines and the pink runs, with dates and distances.",
                f"/collections/{cc}/", lang, CSS_COLLECTION) + f"""
<div class="wrap">
  <div class="crumbs"><a href="/collections/">Collections</a><span>›</span>{esc(cname)}</div>
  <div class="pagehead">
    <div class="eyebrow">Collections · {esc(cname)}</div>
    <h1>Races in {esc(cin)}, <span class="g">sorted by the reason</span> you'd run them</h1>
    <p class="sub">Hand-edited lists from the RunCalendar calendar for runners in {esc(cin)}, plus the world's great races.</p>
  </div>
</div>
<div class="content wide">
  <h2>{esc(cname)}</h2><div class="cards">{"".join(card(c, counts[c["id"]]) for c in own)}</div>
  <h2>Everywhere</h2><div class="cards">{"".join(card(c, counts[c["id"]]) for c in globals_)}</div>
  <div class="tintcard dl">
    <div style="flex:1;min-width:240px"><b style="color:var(--greenDeep)">{TAGLINE}</b><br>Every list here lives in the app, with the dates, the entry openings and a reminder the morning they open. Free on the App Store.</div>
    <a class="btn" href="{STORE}web-{cc}">Get RunCalendar</a>
  </div>
</div>
""" + FOOT
    write(f"/collections/{cc}/", body)


HOME_START, HOME_END = "<!-- COLLECTIONS:START (generated by Tools/website/build_collections.py — do not hand-edit) -->", "<!-- COLLECTIONS:END -->"
LANG_CC = {"gb": "uk", "au": "au", "za": "za", "ca": "ca", "ie": "ie", "nz": "nz", "us": "us"}

def home_section(cols, counts):
    # great-10ks stays OFF the home page (owner 2026-09-20): it lives on /collections/ and in the app;
    # the home section is seven globals + the country card, two rows of four.
    globals_ = [c for c in cols if not c.get("countries") and c["slug"] not in HOME_EXCLUDE]
    # The eighth card (owner 2026-09-20): seven cards read 4 + 3. It stands for every country's own
    # lists under the Chasing a PB photograph and opens the hub — no country is named on the home page.
    pb = next((c for c in cols if c["slug"].startswith("chasing-a-pb-") and c.get("hero_image_url")), None)
    country_card = (f'<a class="ccard" href="/collections/"><div class="ph"><img loading="lazy" src="{esc(pb["hero_image_url"])}" alt=""></div>'
                    f'<div class="cb"><h3>{esc(pb["title"])}</h3><div class="cs">Flat, fast courses in your country</div>'
                    f'<div class="cn">Pick your country ›</div></div></a>') if pb else ""
    return f"""{HOME_START}
<style>
.colsec{{padding:80px 32px 72px}}
.colsec .sub{{font-size:17px;line-height:1.7;color:var(--secondary);max-width:760px;margin:14px auto 0;text-align:center}}
.colsec .cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-top:32px}}
.colsec .ccard{{border:1px solid var(--hairline);border-radius:16px;overflow:hidden;text-decoration:none;color:inherit;background:#fff;display:block}}
.colsec .ph{{aspect-ratio:16/9;background:var(--surface)}}.colsec .ph img{{width:100%;height:100%;object-fit:cover;display:block}}
.colsec .cb{{padding:12px 14px 14px}}.colsec .ccard h3{{font-size:16px;font-weight:800;letter-spacing:-.01em;margin:0}}
.colsec .cs{{font-size:13px;color:var(--secondary);margin-top:3px}}.colsec .cn{{font-size:12px;font-weight:700;color:var(--greenDeep);margin-top:8px}}
.colsec .tag{{font-weight:800;color:var(--greenDeep);font-size:16px;margin:14px auto 0;max-width:640px;text-align:center}}
.colsec .all{{display:block;text-align:center;margin-top:26px;font-weight:800;color:var(--greenDeep);text-decoration:none;font-size:15px}}
/* Phones: the cards are ONE sideways swipe strip, like the app's own (owner 2026-09-21) — eight stacked cards
   were a long scroll before the satellite band. 72% wide so the next card peeks and invites the swipe; the strip
   scrolls inside itself, the page never pans. */
@media(max-width:720px){{.colsec{{padding:56px 0 48px}}.colsec .sech,.colsec .sub,.colsec .tag,.colsec .all{{padding-left:20px;padding-right:20px}}
.colsec .cards{{display:flex;gap:12px;overflow-x:auto;scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;scrollbar-width:none;padding:0 20px 4px;scroll-padding-left:20px;margin-top:26px}}
.colsec .sub .more{{display:none}}.colsec .cards::-webkit-scrollbar{{display:none}}.colsec .ccard{{flex:0 0 72%;scroll-snap-align:start}}}}
</style>
<section class="colsec wrap" id="collections">
  <h2 class="sech">Races, sorted by <span class="g">the reason</span> you'd run them.</h2>
  <p class="sub">Discover the races worth travelling for, the great city halves, epic trails, winter escapes and the world's iconic marathons.<span class="more"> Explore our race guides, or stay closer to home with flat and fast PB courses, brilliant first finish lines, beach runs, trail escapes and races with a cause.</span></p>
  <p class="tag">Every collection is hand-picked. Every race earns its place.</p>
  <div class="cards">{"".join(card(c, counts[c["id"]]) for c in globals_)}{country_card}</div>
  <a class="all" href="/collections/">See all collections, including your country's own ›</a>
</section>
{HOME_END}"""

def write_home(cols, counts):
    p = os.path.join(ROOT, "index.html"); s = open(p).read()
    block = home_section(cols, counts)
    if HOME_START in s:
        s = s[:s.index(HOME_START)] + block + s[s.index(HOME_END) + len(HOME_END):]
    else:
        anchor = "<!-- ================= SATELLITE BAND (the wow) ================= -->"   # collections sit straight under the hero (owner 2026-09-21)
        assert anchor in s, "home page anchor missing"
        s = s.replace(anchor, block + "\n\n" + anchor, 1)
    open(p, "w").write(s)

def main():
    cols = get("/event_collections?status=eq.published&select=id,slug,title,subtitle,description,hook,countries,sort_order,hero_image_url&order=sort_order,slug")
    members = get("/event_collection_members?select=collection_id,event_id,position&limit=5000")
    ids = sorted({m["event_id"] for m in members})
    events = {}
    for i in range(0, len(ids), 80):
        chunk = ",".join(ids[i:i+80])
        for e in get(f"/events?id=in.({chunk})&status=eq.published&select=id,slug,display_name,name,city_name,state_name,state_code,next_event_date,next_date_confirmed,distance_summary,hook,tier,co:countries!country_id(iso_code,name)"):
            if e.get("tier") == "excluded" or not e.get("next_event_date"): continue
            e["name"] = e.get("display_name") or e["name"]
            e["country"] = (e.get("co") or {}).get("iso_code"); e["country_name"] = (e.get("co") or {}).get("name")
            events[e["id"]] = e
    by_col = collections.defaultdict(list)
    for m in members:
        if m["event_id"] in events: by_col[m["collection_id"]].append((m["position"], events[m["event_id"]]))
    counts = {c["id"]: len(by_col[c["id"]]) for c in cols}
    def rank(c):
        iso, mood = mood_of(c); return (MOOD_ORDER.index(mood) if mood in MOOD_ORDER else 99, c["slug"])
    cols.sort(key=rank)
    ev_cols = collections.defaultdict(list)
    urls = ["/collections/"] + [f"/collections/{CC[iso][0]}/" for iso in CC]
    for c in cols:
        evs = [e for _, e in sorted(by_col[c["id"]], key=lambda t: (t[1]["next_event_date"], t[1]["name"]))]
        iso, _ = mood_of(c)
        sibs = [s for s in cols if (mood_of(s)[0] == iso) or not s.get("countries")] if iso else [s for s in cols if not s.get("countries")]
        urls.append(collection_page(c, evs, sibs, None))
        for e in evs: ev_cols[e["id"]].append(c)
    for eid, cs in ev_cols.items(): race_page(events[eid], cs)
    hub(cols, counts)
    write_home(cols, counts)
    for iso in CC: country_hub(iso, cols, counts)
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(f"  <url><loc>{SITE}{u}</loc><lastmod>{TODAY}</lastmod></url>\n" for u in ["/", "/about/", "/add-event/"] + urls) + "</urlset>\n"
    open(os.path.join(ROOT, "sitemap.xml"), "w").write(sm)
    open(os.path.join(ROOT, "robots.txt"), "w").write(f"User-agent: *\nAllow: /\nSitemap: {SITE}/sitemap.xml\n")
    print(f"collections {len(cols)} · races {len(ev_cols)} · sitemap urls {len(urls) + 3}")

if __name__ == "__main__": main()
