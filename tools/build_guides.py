#!/usr/bin/env python3
"""Generate the race GUIDES on runcalendar.com (owner decision 10 Nov 2026, stages 1 + 2 together):

    /race/<event slug>/guide/      one page per PUBLISHED featured guide whose race is visible (the app's rule)
    /guides/                       the hub: every guide, grouped by month like the app's Race Guides list
    /collections/race-guides/      forwards to /guides/ (the old collection address stays alive)
    sitemap-guides.xml             + its entry in sitemap.xml

    python3 Tools/website/build_guides.py [--out <dir>]

Runs AFTER build_collections.py and build_catalogue.py (it imports the catalogue generator for the page chrome,
the race facts and the shared stylesheet hash, so the three always agree). Reads the public anon REST endpoint —
published rows only. The guide text is EVERGREEN by rule (no prices, no "entries open now" in prose); the one
edition-specific thing, the per-distance entry pill, refreshes with the nightly rebuild.

Design: Design/website_guide_mock.html (owner-approved 10 Nov 2026). Section order = the app's Guide screen:
quick verdict → course at a glance (stat tiles, text) → distances → where you'll feel it (📍 toughest climb) →
best chance to push → three things → race-day weather (stat tiles) → what runners wear → typical finish times →
worth the trip. A NULL module never renders. The course map is a later pass (nothing renders in its place).
"""
import json, os, re, sys, datetime, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_catalogue as C
from build_catalogue import (esc, head, FOOT, write, get, STORE, SITE, TAGLINE, TODAY, ROOT, EVENT_SELECT, chips, legs, dist_line,
                             place_short, place_long, weekday_date, long_date, month_year, iso, cslug, ename, edition, frame, fetch_manifest,
                             visible_in_lists, mi_text, km_text, in_country)

GUIDE_SELECT = ("id,slug,title,tagline,hero_image_url,quick_verdict,course_at_a_glance,where_youll_feel_it,three_things,race_day_weather,"
                "what_runners_wear,toughest_climb,best_chance_to_push,typical_finish_times,worth_the_trip,course_stats,conditions_stats,"
                "distances,event_id,updated_at,published_at")

def fetch_guides():
    guides = get(f"/featured_guides?select={GUIDE_SELECT}&status=eq.published&order=slug")
    ids = ",".join(sorted({g["event_id"] for g in guides}))
    # the race facts exactly as the catalogue reads them (next edition only, visibility rule)
    events = get(f"/events?select={EVENT_SELECT}&id=in.({ids})&status=eq.published&or=(tier.eq.core,tier.eq.local,tier.is.null)"
                 f"&next_event_date=gte.{TODAY.isoformat()}&event_editions.event_date=gte.{TODAY.isoformat()}"
                 f"&event_editions.order=event_date&event_editions.limit=1&order=id")
    by_id = {e["id"]: e for e in events}
    out = []
    for g in guides:
        e = by_id.get(g["event_id"])
        if not e: print(f"  skip {g['slug']}: race not visible", file=sys.stderr); continue
        out.append((g, e))
    return out

def fetch_hub_collection():
    rows = get("/event_collections?select=title,subtitle,description,hero_image_url&slug=eq.race-guides&status=eq.published")
    return rows[0] if rows else {}

# ---------------------------------------------------------------- pieces
def guide_path(e): return f"/race/{e['slug']}/guide/"

def para(text):
    # a module is one or more paragraphs; blank lines split them
    parts = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    return "".join(f"<p>{esc(p)}</p>" for p in parts)

def tiles(stats):
    items = [s for s in (stats or []) if isinstance(s, dict) and s.get("value")]
    if not items: return ""
    return '<div class="tiles stats">' + "".join(f'<div class="tile"><b>{esc(str(s["value"]))}</b><span>{esc(str(s.get("label") or ""))}</span></div>' for s in items) + "</div>"

def leg_unit(e, km):
    # the event's own unit for a distance card (3% match against the edition's legs)
    for l in (edition(e).get("event_distances") or []):
        lk = l.get("distance_km")
        if lk and km and abs(lk - km) / km <= 0.03: return l.get("source_unit")
    return None

def distance_cards(g, e):
    ds = [d for d in (g.get("distances") or []) if isinstance(d, dict) and d.get("label")]
    if not ds: return ""
    out = ""
    for d in ds:
        km = d.get("km")
        try: km = float(km) if km is not None else None
        except (TypeError, ValueError): km = None
        kmtxt = (mi_text(km) if leg_unit(e, km) == "mi" else km_text(km)) if km else ""
        st = (d.get("entry_state") or "").lower()
        cls = "open" if st == "open" else ("later" if st in ("later", "opens_later", "not_yet_open") else "")
        txt = d.get("entry_text") or {"open": "Entries open", "closed": "Entries closed", "later": "Entries open later", "opens_later": "Entries open later", "not_yet_open": "Entries open later"}.get(st, "")
        out += f'''<div class="dist">
    <div class="top"><h3>{esc(d["label"])}</h3>{f'<span class="km">{esc(kmtxt)}</span>' if kmtxt else ''}{'<span class="mostrun">Most run</span>' if d.get("most_run") else ''}</div>
    {f'<div class="meta">{esc(d["meta"])}</div>' if d.get("meta") else ''}
    {f'<p>{esc(d["who"])}</p>' if d.get("who") else ''}
    {f'<p>{esc(d["course"])}</p>' if d.get("course") else ''}
    {f'<span class="entry {cls}">{esc(txt)}</span>' if txt else ''}
  </div>'''
    return "<h2>Distances</h2>" + out

def things(g):
    tt = g.get("three_things")
    if isinstance(tt, dict): tt = list(tt.values())
    items = [t if isinstance(t, str) else (t.get("text") or t.get("body") or "") for t in (tt or []) if t]
    items = [t for t in items if t.strip()]
    if not items: return ""
    return '<h2>Three things to know</h2><ol class="things">' + "".join(f"<li>{esc(t)}</li>" for t in items) + "</ol>"

def guide_chips(e):
    ch = chips(e)
    dl = dist_line(e)
    if dl and len(dl) <= 44:
        # distances sit before the entry-state chip, like the mock
        tail = [c for c in ch if c[1].startswith("Entries") or c[1] == "Sold out"]
        ch = [c for c in ch if c not in tail] + [("", dl)] + tail
    return "".join(f'<span class="chip {k}">{esc(t)}</span>' for k, t in ch)

def save_script(cc, deep):
    return f"""<script>
(function(){{
  var from = new URLSearchParams(location.search).get('from');
  var store = "{STORE}" + (from ? from : "web-{cc}-guide");
  var btn = document.getElementById('open'); btn.href = store;
  var deep = "{deep}";
  if (/iPhone|iPad|iPod/.test(navigator.userAgent)) btn.addEventListener('click', function(ev){{
    ev.preventDefault();
    var f = document.createElement('iframe'); f.style.display = 'none'; f.src = deep; document.body.appendChild(f);
    setTimeout(function(){{ if (!document.hidden) location.href = store; }}, 1200);
  }});
}})();
</script>"""

# ---------------------------------------------------------------- the guide page
def guide_page(g, e, manifest):
    code = iso(e); cc = cslug(code); cname = (e.get("country") or {}).get("name") or ""
    path = guide_path(e); name = g.get("title") or ename(e)
    confirmed = bool(e.get("next_date_confirmed"))
    when = long_date(e["next_event_date"]) if confirmed else month_year(e["next_event_date"])
    short_date = weekday_date(e["next_event_date"]) if confirmed else month_year(e["next_event_date"])
    img = g.get("hero_image_url") or frame(manifest, e)
    region = e.get("state_name") or ""
    rslug = C.slugify(region) if region else ""
    crumbs = (f'<a href="/races/">Races</a><span>›</span><a href="/races/{cc}/">{esc(cname)}</a><span>›</span>'
              + (f'<a href="/races/{cc}/{rslug}/">{esc(region)}</a><span>›</span>' if region else "")
              + f'<a href="/race/{e["slug"]}/">{esc(ename(e))}</a><span>›</span>Race guide')
    climb = g.get("toughest_climb")
    sections = [
        ("Quick verdict", para(g.get("quick_verdict"))),
        ("Course at a glance", tiles(g.get("course_stats")) + para(g.get("course_at_a_glance"))),
        (None, distance_cards(g, e)),
        ("Where you'll feel it", (f'<div class="pin"><span class="ic">📍</span><span>{esc(climb)}</span></div>' if climb else "") + para(g.get("where_youll_feel_it"))),
        ("Best chance to push", para(g.get("best_chance_to_push"))),
        (None, things(g)),
        ("Race-day weather", tiles(g.get("conditions_stats")) + para(g.get("race_day_weather"))),
        ("What runners wear", para(g.get("what_runners_wear"))),
        ("Typical finish times", para(g.get("typical_finish_times"))),
        ("Worth the trip?", para(g.get("worth_the_trip"))),
    ]
    body_html = ""
    for h, inner in sections:
        if not inner or (h and inner.strip() in ("", tiles(None))): continue
        if h and not re.sub(r"<div class=\"tiles stats\">.*?</div></div>", "", inner, flags=re.S).strip() and "tiles" not in inner: continue
        body_html += (f"<h2>{esc(h)}</h2>" if h else "") + inner
    tagline = g.get("tagline") or e.get("hook") or ""
    meta_desc = f"{name} race guide: " + (tagline if len(tagline) < 120 else tagline[:117].rsplit(" ", 1)[0] + "…") + f" {short_date}."
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": f"{name} race guide", "description": tagline,
          "url": SITE + path, "mainEntityOfPage": SITE + path, "inLanguage": "en",
          "datePublished": (g.get("published_at") or g.get("updated_at") or "")[:10], "dateModified": (g.get("updated_at") or "")[:10],
          "author": {"@type": "Organization", "name": "RunCalendar", "url": SITE},
          "publisher": {"@type": "Organization", "name": "RunCalendar", "url": SITE, "logo": {"@type": "ImageObject", "url": SITE + "/assets/appicon-180.png"}},
          "about": {"@type": "SportsEvent", "name": ename(e), "sport": "Running", "url": SITE + f"/race/{e['slug']}/", "startDate": e["next_event_date"],
                    "endDate": e["next_event_date"], "eventStatus": "https://schema.org/EventScheduled", "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                    "description": tagline or e.get("hook") or ename(e),
                    "location": {"@type": "Place", "name": place_short(e) or cname, "address": {"@type": "PostalAddress", "addressLocality": e.get("city_name") or "", "addressRegion": region, "addressCountry": code}}}}
    if img: ld["image"] = img; ld["about"]["image"] = img
    ed = edition(e)
    if e.get("website"):
        ld["about"]["organizer"] = {"@type": "Organization", "name": e["name"], "url": e["website"]}
        avail = "https://schema.org/SoldOut" if (ed.get("sold_out") or ed.get("registration_state") == "sold_out") else ("https://schema.org/InStock" if ed.get("registration_state") == "open" else None)
        if avail:
            ld["about"]["offers"] = {"@type": "Offer", "availability": avail, "url": e["website"]}
            if ed.get("registration_closes"): ld["about"]["offers"]["validThrough"] = ed["registration_closes"]
    lang = {"US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA", "IE": "en-IE", "NZ": "en-NZ", "ZA": "en-ZA"}.get(code, "en")
    body = head(f"{name} race guide — course, climbs and race-day detail | RunCalendar", meta_desc, path, lang, ld=ld, og_image=img) + f"""
<div class="wrap">
  <div class="crumbs">{crumbs}</div>
  <div class="hero photo{'' if img else ' nopic'}">{f'<img src="{esc(img)}" alt="{esc(name)}">' if img else '<span class="grad"></span>'}</div>
  <div class="racehead">
    <div class="when">Race guide · {esc(when)}</div>
    <h1>{esc(name)}</h1>
    <div class="place">{esc(place_long(e))}</div>
    <div class="chips">{guide_chips(e)}</div>
    {f'<p class="standfirst">{esc(tagline)}</p>' if tagline else ''}
    <div class="saverow"><a class="savebtn" id="open" href="{STORE}web-{cc}-guide">Save to my season</a><div class="small">Opens in RunCalendar.<br>Free on iPhone · No account needed.</div></div>
  </div>
</div>

<div class="content">
  {body_html}

  {C.cta(f"web-{cc}-guide", f"Save {esc(ename(e))} to your season and RunCalendar reminds you the morning entries open and before they close. Free on iPhone, no account needed.")}

  <div class="foot">
    <div class="claim"><a href="/race/{e['slug']}/">{esc(ename(e))} on the calendar: date, distances and key dates ›</a></div>
    {f'<a class="site" href="{esc(e["website"])}" rel="nofollow noopener">Visit event website ›</a>' if e.get("website") else ''}
  </div>
  <p class="fine">Written by RunCalendar from the organiser's own published information and past editions. Entry states are checked nightly; everything else is written to last the season. This page is rebuilt every night from the RunCalendar catalogue.</p>
</div>
{save_script(cc, "runcalendar://guide/" + g["slug"])}
""" + FOOT
    write(path, body)

# ---------------------------------------------------------------- the hub
def hub_row(g, e, manifest):
    href = guide_path(e); img = g.get("hero_image_url") or frame(manifest, e)
    sq = f'<img src="{esc(img)}" alt="" loading="lazy">' if img else '<span class="grad"></span>'
    date = weekday_date(e["next_event_date"], False) if e.get("next_date_confirmed") else month_year(e["next_event_date"])
    dist = dist_line(e)
    place = place_short(e); cname = (e.get("country") or {}).get("name") or ""
    where = place if place.lower() == cname.lower() else ((place + " · " if place else "") + cname)   # Singapore, not "Singapore · Singapore"
    tag = f'<p class="hook">{esc(g["tagline"])}</p>' if g.get("tagline") else ""
    return f'''<li class="race">
  <a class="sq" href="{href}">{sq}</a>
  <div class="t"><h3><a href="{href}">{esc(g.get("title") or ename(e))}</a> <span class="gbadge">Guide</span></h3><div class="meta"><b>{esc(date)}</b> · {esc(where)}{(" · " + esc(dist)) if dist else ""}</div>{tag}</div>
  <div class="acts"><a class="save" href="{href}">Read the guide</a></div>
</li>'''

def hub(pairs, manifest, col):
    pairs = sorted(pairs, key=lambda p: (p[1]["next_event_date"], p[1]["id"]))
    groups = collections.OrderedDict()
    for g, e in pairs: groups.setdefault(e["next_event_date"][:7], []).append((g, e))
    rows = ""
    for mk, items in groups.items():
        label = datetime.date(int(mk[:4]), int(mk[5:]), 1).strftime("%B %Y")
        rows += f'<div class="label">{esc(label)} <span class="r">{len(items)} guide{"s" if len(items) != 1 else ""}</span></div><ul class="races">' + "".join(hub_row(g, e, manifest) for g, e in items) + "</ul>"
    n = len(pairs)
    sub = (col.get("description") or "Every race here has a full RunCalendar guide: the course and where the climbs are, what race day is like, what to wear, typical finish times and whether it is worth the trip.")
    desc = f"{n} race guides from RunCalendar: course, climbs, entries and race-day detail for the world's great races, from the Majors to the big trail weekends. {TAGLINE}"
    img = col.get("hero_image_url")
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Race guides", "url": SITE + "/guides/",
          "hasPart": [{"@type": "Article", "headline": f"{g.get('title') or ename(e)} race guide", "url": SITE + guide_path(e)} for g, e in pairs]}
    body = head("Race guides — course, climbs and race-day detail | RunCalendar", desc, "/guides/", ld=ld, og_image=img) + f"""
<div class="wrap">
  <div class="crumbs">Race guides</div>
  <div class="pagehead" style="max-width:760px;margin:0 auto">
    <div class="eyebrow">Race guides · Worldwide</div>
    <h1>Race guides</h1>
    <p class="sub">{esc(sub)} {n} guides, in date order. Written to last the season; entry states checked nightly.</p>
  </div>
  {f'<div class="hero photo"><img src="{esc(img)}" alt="Race guides"></div>' if img else ''}
</div>
<div class="content">
  {rows}
  {C.cta("web-guides", "Every guide lives in the app beside the race itself, with the dates, the entry openings and a reminder the morning they open. Free on iPhone, no account needed.")}
  <p class="fine">Each guide is written by RunCalendar from the organiser's own published information and past editions, and rebuilt every night from the catalogue. A confirmed date shows its day; a provisional one shows only its month. Last updated {TODAY.strftime("%-d %B %Y")}.</p>
</div>
""" + FOOT
    write("/guides/", body)

def redirect_page():
    # the old collection address keeps working: a static host has no server redirects, so the page forwards itself
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Race guides | RunCalendar</title>
<meta http-equiv="refresh" content="0; url=/guides/"><link rel="canonical" href="{SITE}/guides/"><meta name="robots" content="noindex,follow">
<script>location.replace("/guides/" + location.search);</script></head>
<body><p>The race guides have moved to <a href="/guides/">runcalendar.com/guides</a>.</p></body></html>
"""
    write("/collections/race-guides/", body)

def sitemaps(pairs):
    urls = ["/guides/"] + [guide_path(e) for _, e in pairs]
    with open(os.path.join(ROOT, "sitemap-guides.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for u in urls: f.write(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n")
        f.write("</urlset>\n")
    idx = os.path.join(ROOT, "sitemap.xml")
    try: s = open(idx).read()
    except FileNotFoundError: return
    if "sitemap-guides.xml" not in s:
        s = s.replace("</sitemapindex>", f"<sitemap><loc>{SITE}/sitemap-guides.xml</loc><lastmod>{TODAY.isoformat()}</lastmod></sitemap>\n</sitemapindex>")
        open(idx, "w").write(s)

# ---------------------------------------------------------------- main
def main():
    os.makedirs(ROOT, exist_ok=True)
    print("fetching guides…", file=sys.stderr)
    pairs = fetch_guides()
    manifest = fetch_manifest()
    col = fetch_hub_collection()
    for g, e in pairs: guide_page(g, e, manifest)
    hub(pairs, manifest, col)
    redirect_page()
    sitemaps(pairs)
    print(f"guides: {len(pairs)} pages + /guides/ into {ROOT}", file=sys.stderr)

if __name__ == "__main__":
    main()
