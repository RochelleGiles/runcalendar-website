#!/usr/bin/env python3
"""Generate the catalogue on runcalendar.com: /races/ hubs (world → country → region → month)
and one /race/<slug>/ page for every upcoming visible race.

    python3 Tools/website/build_catalogue.py [--out <dir>] [--only US,GB]

Reads the public anon REST endpoint (published rows only — the app's own visibility rule:
status = published, tier ≠ excluded, next_event_date ≥ today). Writes into website/ by default
(the hand-made pages' source of truth); the nightly job writes straight into the deploy clone.
Generated directories (/races/, /race/, sitemap*.xml, search indexes) are NOT committed to the
app repo — they are rebuilt nightly in the website repository's own workflow.

Design: Design/web_catalogue_mock (owner-approved 12 Oct 2026). Satellite frames come from the
manifest the snapshot fetcher writes to the public `web-assets` bucket; a race without a frame
gets the brand gradient, never an empty box.
"""
import json, re, html, datetime, os, sys, urllib.request, urllib.parse, collections, unicodedata

REST = "https://rteqvslwxgsgvccrgtzg.supabase.co/rest/v1"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ0ZXF2c2x3eGdzZ3ZjY3JndHpnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2NDExOTUsImV4cCI6MjA1OTIxNzE5NX0.9nS2ATC2p2bfruWNhKylrIPamtYfnb6hTSyv5GC5Ksw"
BUCKET = "https://rteqvslwxgsgvccrgtzg.supabase.co/storage/v1/object/public"
MANIFEST = BUCKET + "/web-assets/sat/manifest.json"
SITE = "https://runcalendar.com"
STORE = "https://apps.apple.com/app/apple-store/id6726998429?pt=2876806&mt=8&ct="
TAGLINE = "Your next race, seen from above."
TODAY = datetime.date.today()
HORIZON_HIDE_DAYS = 60          # a provisional date inside 60 days is hidden from lists (app rule 2026-09-04)
COMING_UP = 10
PAGE = 1000

args = sys.argv[1:]
ROOT = os.path.abspath(args[args.index("--out") + 1]) if "--out" in args else os.environ.get("SITE_ROOT") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "website")
ONLY = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None

# Countries whose region codes read at a glance (the app's placeShort rule)
CODE_COUNTRIES = {"US", "AU", "CA"}
# Country slugs: the download markets keep their short, familiar slugs; everything else is the ISO code lowercased
CC_SLUG = {"GB": "uk"}
# Owner-chosen hero places per country (event slug); a country not listed leads with its first core race
HERO = {"US": "130th-boston-marathon", "GB": "london-marathon", "AU": "sydney-marathon", "ZA": "cape-town-marathon",
        "CA": "2026-bmo-vancouver-marathon-international", "IE": "dublin-marathon", "NZ": "queenstown-marathon",
        "FR": "paris-marathon", "DE": "bmw-berlin-marathon", "JP": "tokyo-marathon", "ES": "valencia-marathon", "IT": "run-rome-the-marathon", "IN": "tata-mumbai-marathon"}
MAIN_MARKETS = ["US", "GB", "AU", "ZA", "CA", "IE", "NZ"]
# countries whose name takes "the" in a sentence ("races in the United States")
THE = {"US", "GB", "NL", "PH", "AE", "CZ", "DO", "BS", "MV", "GM", "CD", "CF", "KM", "SC", "MH", "SB", "VG", "VI", "KY", "TC", "FO", "IM"}
def in_country(code, name): return ("the " + name) if code in THE else name
US_ADJ = {"Alabama":["Florida","Georgia","Mississippi","Tennessee"],"Alaska":[],"Arizona":["California","Colorado","Nevada","New Mexico","Utah"],"Arkansas":["Louisiana","Mississippi","Missouri","Oklahoma","Tennessee","Texas"],"California":["Arizona","Nevada","Oregon"],"Colorado":["Arizona","Kansas","Nebraska","New Mexico","Oklahoma","Utah","Wyoming"],"Connecticut":["Massachusetts","New York","Rhode Island"],"Delaware":["Maryland","New Jersey","Pennsylvania"],"District of Columbia":["Maryland","Virginia"],"Florida":["Alabama","Georgia"],"Georgia":["Alabama","Florida","North Carolina","South Carolina","Tennessee"],"Hawaii":[],"Idaho":["Montana","Nevada","Oregon","Utah","Washington","Wyoming"],"Illinois":["Indiana","Iowa","Kentucky","Missouri","Wisconsin"],"Indiana":["Illinois","Kentucky","Michigan","Ohio"],"Iowa":["Illinois","Minnesota","Missouri","Nebraska","South Dakota","Wisconsin"],"Kansas":["Colorado","Missouri","Nebraska","Oklahoma"],"Kentucky":["Illinois","Indiana","Missouri","Ohio","Tennessee","Virginia","West Virginia"],"Louisiana":["Arkansas","Mississippi","Texas"],"Maine":["New Hampshire"],"Maryland":["Delaware","District of Columbia","Pennsylvania","Virginia","West Virginia"],"Massachusetts":["Connecticut","New Hampshire","New York","Rhode Island","Vermont"],"Michigan":["Indiana","Ohio","Wisconsin"],"Minnesota":["Iowa","North Dakota","South Dakota","Wisconsin"],"Mississippi":["Alabama","Arkansas","Louisiana","Tennessee"],"Missouri":["Arkansas","Illinois","Iowa","Kansas","Kentucky","Nebraska","Oklahoma","Tennessee"],"Montana":["Idaho","North Dakota","South Dakota","Wyoming"],"Nebraska":["Colorado","Iowa","Kansas","Missouri","South Dakota","Wyoming"],"Nevada":["Arizona","California","Idaho","Oregon","Utah"],"New Hampshire":["Maine","Massachusetts","Vermont"],"New Jersey":["Delaware","New York","Pennsylvania"],"New Mexico":["Arizona","Colorado","Oklahoma","Texas","Utah"],"New York":["Connecticut","Massachusetts","New Jersey","Pennsylvania","Vermont"],"North Carolina":["Georgia","South Carolina","Tennessee","Virginia"],"North Dakota":["Minnesota","Montana","South Dakota"],"Ohio":["Indiana","Kentucky","Michigan","Pennsylvania","West Virginia"],"Oklahoma":["Arkansas","Colorado","Kansas","Missouri","New Mexico","Texas"],"Oregon":["California","Idaho","Nevada","Washington"],"Pennsylvania":["Delaware","Maryland","New Jersey","New York","Ohio","West Virginia"],"Rhode Island":["Connecticut","Massachusetts"],"South Carolina":["Georgia","North Carolina"],"South Dakota":["Iowa","Minnesota","Montana","Nebraska","North Dakota","Wyoming"],"Tennessee":["Alabama","Arkansas","Georgia","Kentucky","Mississippi","Missouri","North Carolina","Virginia"],"Texas":["Arkansas","Louisiana","New Mexico","Oklahoma"],"Utah":["Arizona","Colorado","Idaho","Nevada","New Mexico","Wyoming"],"Vermont":["Massachusetts","New Hampshire","New York"],"Virginia":["District of Columbia","Kentucky","Maryland","North Carolina","Tennessee","West Virginia"],"Washington":["Idaho","Oregon"],"West Virginia":["Kentucky","Maryland","Ohio","Pennsylvania","Virginia"],"Wisconsin":["Illinois","Iowa","Michigan","Minnesota"],"Wyoming":["Colorado","Idaho","Montana","Nebraska","South Dakota","Utah"]}

# ---------------------------------------------------------------- fetch
def get(path, tries=4):
    req = urllib.request.Request(REST + path, headers={"apikey": ANON, "Authorization": "Bearer " + ANON})
    for i in range(tries):
        try: return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except Exception as e:
            if i == tries - 1: raise
            print(f"  retry {i + 1} after {e}", file=sys.stderr); import time; time.sleep(3 * (i + 1))

def get_all(path):
    out, off = [], 0
    while True:
        chunk = get(path + f"&limit={PAGE}&offset={off}")
        out += chunk
        if len(chunk) < PAGE: return out
        off += PAGE

EVENT_SELECT = ("id,slug,name,display_name,hook,description,course_summary,scenery_tags,event_type,trail_pct,website,distance_summary,"
                "city_name,state_name,state_code,next_event_date,next_date_confirmed,tier,"
                "primary_city:cities!primary_city_id(lat,lng),country:countries!country_id(name,iso_code),"
                "event_editions(event_date,date_confirmed,registration_opens,registration_closes,registration_state,sold_out,edition_year,"
                "event_distances(title,distance_km,source_unit,elevation_gain_m,cutoff_minutes,is_timed_event,timed_duration_minutes))")

def fetch_events():
    q = (f"/events?select={EVENT_SELECT}&status=eq.published&or=(tier.eq.core,tier.eq.local,tier.is.null)"
         f"&next_event_date=gte.{TODAY.isoformat()}&event_editions.event_date=gte.{TODAY.isoformat()}"
         f"&event_editions.order=event_date&event_editions.limit=1&order=id")
    return get_all(q)

def fetch_collections():
    cols = get("/event_collections?select=id,slug,title,subtitle,hook,hero_image_url,countries,sort_order,strip_order&status=eq.published&order=sort_order")
    members = get_all("/event_collection_members?select=collection_id,event_id&order=collection_id,position")
    by_col = collections.defaultdict(list)
    for m in members: by_col[m["collection_id"]].append(m["event_id"])
    for c in cols: c["members"] = by_col.get(c["id"], [])
    return cols

def fetch_manifest():
    try:
        req = urllib.request.Request(MANIFEST + "?t=" + str(datetime.datetime.now().timestamp()))
        raw = json.loads(urllib.request.urlopen(req, timeout=60).read())
        # a JSON list of event ids (the fetcher's format since 12 Oct); an older dict of id → url still works
        return {i: BUCKET + "/web-assets/sat/" + i + ".jpg" for i in raw} if isinstance(raw, list) else raw
    except Exception as e:
        print("no satellite manifest yet:", e, file=sys.stderr); return {}

# ---------------------------------------------------------------- helpers
def esc(s): return html.escape(s or "", quote=True)

def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"['’]", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s or "other"

def d(s): return datetime.date.fromisoformat(s)
def weekday_date(s, year_always=True):
    dt = d(s); return dt.strftime("%a %-d %b %Y") if year_always or dt.year != TODAY.year else dt.strftime("%a %-d %b")
def long_date(s): return d(s).strftime("%A %-d %B %Y")
def month_year(s): return d(s).strftime("%B %Y")
def month_key(s): return s[:7]
def month_label(key, with_year=False):
    dt = datetime.date(int(key[:4]), int(key[5:]), 1)
    return dt.strftime("%b %Y") if with_year or dt.year != TODAY.year or key[5:] == "01" else dt.strftime("%b")
def relative(s):
    n = (d(s) - TODAY).days
    if n < 0: return ""
    if n == 0: return "today"
    if n == 1: return "tomorrow"
    if n < 15: return f"in {n} days"
    w = round(n / 7); return f"in {w} week{'s' if w != 1 else ''}"

def ename(e): return e.get("display_name") or e["name"]
def iso(e): return (e.get("country") or {}).get("iso_code") or ""
def cslug(code): return CC_SLUG.get(code, code.lower())
def region_short(e):
    code, name = e.get("state_code"), e.get("state_name")
    if iso(e) in CODE_COUNTRIES and code: return code.split("-")[-1]
    if name and name.lower() != (e.get("city_name") or "").lower(): return name
    return ""
def place_short(e):
    r = region_short(e); c = e.get("city_name") or ""
    return f"{c}, {r}" if r and c else (c or r)
def place_long(e):
    c = e.get("city_name") or ""; n = e.get("state_name") or ""
    p = c if not n or n.lower() == c.lower() else (f"{c}, {n}" if c else n)
    return p + " · " + ((e.get("country") or {}).get("name") or "")

def edition(e):
    eds = e.get("event_editions") or []
    return eds[0] if eds else {}

def visible_in_lists(e):
    # the app's feedScope: a provisional date inside 60 days is hidden from browse
    if e.get("next_date_confirmed") is False and d(e["next_event_date"]) < TODAY + datetime.timedelta(days=HORIZON_HIDE_DAYS): return False
    return True

def indexable(e):
    # index what Google can trust: a confirmed day, or an edited hook line
    return bool(e.get("next_date_confirmed")) or bool(e.get("hook"))

NAMES = {5: "5K", 8: "5 miles", 10: "10K", 15: "15K", 16.1: "10 miles", 21.1: "Half marathon", 42.2: "Marathon", 50: "50K", 80.5: "50 miles", 100: "100K", 160.9: "100 miles"}
def std_name(km):
    for k, v in NAMES.items():
        if abs(km - k) <= (0.15 if k < 30 else 0.6): return v
    return None
def km_text(km): return f"{round(km, 1):g} km"
def mi_text(km): return f"{km / 1.609344:.1f} mi".replace(".0 mi", " mi")

def legs(e):
    out = []
    for l in (edition(e).get("event_distances") or []):
        km = l.get("distance_km")
        if l.get("is_timed_event") and l.get("timed_duration_minutes"):
            h = l["timed_duration_minutes"] / 60
            out.append({"title": (l.get("title") or f"{h:g} Hour")[:28], "sub": "timed", "km": 10 ** 6 + h})
        elif km and km >= 0.1:
            t = l.get("title") or ""
            title = t if 0 < len(t) <= 18 else (std_name(km) or km_text(km))
            unit = l.get("source_unit")
            sub = mi_text(km) if unit == "mi" else km_text(km)
            out.append({"title": title, "sub": sub, "km": km})
    seen, uniq = set(), []
    for l in sorted(out, key=lambda x: -x["km"]):
        k = (l["title"].lower(), l["sub"])
        if k not in seen: seen.add(k); uniq.append(l)
    return uniq[:6]

def dist_line(e):
    # the card's distance text: standard names where they exist, in the event's own unit
    ls = legs(e)
    if ls: return " · ".join(l["title"] for l in ls)
    s = (e.get("distance_summary") or "").strip()
    if not s: return ""
    m = re.match(r"^(.*?)\s*(k|km|mi)$", s); unit = "km"
    if m: s, unit = m.group(1), ("mi" if m.group(2) == "mi" else "km")
    parts = []
    for p in re.split(r"\s*/\s*", s):
        try: v = float(p)
        except ValueError: parts.append(p); continue
        parts.append((std_name(v) if unit == "km" else None) or f"{p} {unit}")
    return " · ".join(parts)

TYPE = {"road": "Road", "trail": "Trail", "mountain": "Mountain", "track": "Track", "ultra": "Ultra", "fun_run": "Fun run", "relay": "Relay", "stage_race": "Stage race", "obstacle": "Obstacle", "multi_day": "Multi-day"}
def chips(e):
    out = []
    t = TYPE.get(e.get("event_type") or "")
    if t: out.append(("", t))
    tags = e.get("scenery_tags") or []
    if tags: out.append(("", tags[0].replace("_", " ").capitalize()))
    tp = e.get("trail_pct")
    if tp and tp >= 1 and t != "Trail": out.append(("g", f"{tp}% trail"))
    ed = edition(e)
    if ed.get("sold_out") or ed.get("registration_state") == "sold_out": out.append(("n", "Sold out"))
    elif ed.get("registration_state") == "open": out.append(("g", "Entries open"))
    elif ed.get("registration_opens") and d(ed["registration_opens"]) > TODAY: out.append(("g", "Entries open " + weekday_date(ed["registration_opens"], False)))
    return out

def key_dates(e):
    ed = edition(e); rows = []
    opens, closes, state = ed.get("registration_opens"), ed.get("registration_closes"), ed.get("registration_state")
    sold = ed.get("sold_out") or state == "sold_out"
    if opens:
        if d(opens) <= TODAY: rows.append(("n", "✓", "Entries opened", weekday_date(opens), ""))
        else: rows.append(("g", "!", "Entries open", weekday_date(opens) + " · " + relative(opens), "g"))
    elif state == "open": rows.append(("g", "!", "Registration", "Open now", "g"))
    elif state == "not_yet_open": rows.append(("n", "·", "Registration", "Not open yet", ""))
    elif state == "closed" and not sold: rows.append(("n", "✓", "Registration", "Closed", ""))
    if sold: rows.append(("n", "·", "Entries", "Sold out", ""))
    elif closes:
        if d(closes) < TODAY: rows.append(("n", "✓", "Entries closed", weekday_date(closes), ""))
        else: rows.append(("g", "!", "Entries close", weekday_date(closes) + " · " + relative(closes), ""))
    if e.get("next_date_confirmed"): rows.append(("gold", "★", "Race day", weekday_date(e["next_event_date"]), ""))
    else: rows.append(("gold", "★", "Race day", month_year(e["next_event_date"]) + " · date to be announced", ""))
    return rows

# ---------------------------------------------------------------- page chrome
CSS_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogue.css")

def head(title, desc, canonical, lang="en", ld=None, og_image=None, noindex=False):
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
<link rel="stylesheet" href="/_catalogue.css">
{('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + '</script>') if ld else ''}
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

SEARCH_JS = """
<script>
(function(){
  var box=document.getElementById('q'), out=document.getElementById('qout'), idx=null, src=box.getAttribute('data-index');
  function norm(s){return s.toLowerCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g,'');}
  function render(q){
    if(!idx){out.innerHTML='';return;}
    var words=norm(q).split(/\\s+/).filter(Boolean); if(!words.length){out.innerHTML='';out.style.display='none';return;}
    var hits=[]; for(var i=0;i<idx.length;i++){var r=idx[i],h=r[5]; var ok=true; for(var w=0;w<words.length;w++){if(h.indexOf(words[w])<0){ok=false;break;}} if(ok){var nm=norm(r[1]); var sc=0; for(var w2=0;w2<words.length;w2++){if(nm.indexOf(words[w2])<0)sc++;} hits.push([sc,i,r]);}}
    hits.sort(function(a,b){return a[0]-b[0]||a[1]-b[1];}); hits=hits.slice(0,12).map(function(x){return x[2];});
    if(!hits.length){out.innerHTML='<div class="qnone">Nothing matches yet — try the race name or its town.</div>';out.style.display='block';return;}
    out.innerHTML=hits.map(function(r){return '<a href="/race/'+r[0]+'/"><b>'+r[1]+'</b><span>'+r[3]+' · '+r[2]+(r[4]?' · '+r[4]:'')+'</span></a>';}).join('');
    out.style.display='block';
  }
  box.addEventListener('input',function(){ var q=box.value; if(!idx){fetch(src).then(function(r){return r.json();}).then(function(j){idx=j;render(box.value);});} else render(q); });
  document.addEventListener('click',function(ev){ if(!out.contains(ev.target)&&ev.target!==box){out.style.display='none';} });
  box.addEventListener('focus',function(){ if(box.value) render(box.value); });
})();
</script>
"""

written = []
def write(path, content):
    dd = os.path.join(ROOT, path.strip("/"))
    os.makedirs(dd, exist_ok=True)
    fp = os.path.join(dd, "index.html")
    new = content.encode()
    try:
        if open(fp, "rb").read() == new: written.append(path); return
    except FileNotFoundError: pass
    with open(fp, "wb") as f: f.write(new)
    written.append(path)

def frame(manifest, e):
    return manifest.get(e["id"])

def row(e, token, manifest):
    href = f"/race/{e['slug']}/"
    img = frame(manifest, e)
    sq = f'<img src="{esc(img)}" alt="" loading="lazy">' if img else '<span class="grad"></span>'
    date = weekday_date(e["next_event_date"], False) if e.get("next_date_confirmed") else month_year(e["next_event_date"])
    dist = dist_line(e)
    hook = f'<p class="hook">{esc(e["hook"])}</p>' if e.get("hook") else ""
    return f'''<li class="race">
  <a class="sq" href="{href}">{sq}</a>
  <div class="t"><h3><a href="{href}">{esc(ename(e))}</a></h3><div class="meta"><b>{esc(date)}</b> · {esc(place_short(e))}{(" · " + esc(dist)) if dist else ""}</div>{hook}</div>
  <div class="acts"><a class="save" href="{STORE}{token}">Save</a></div>
</li>'''

def cta(token, line="Save any of these to your season in RunCalendar and hear the morning entries open. Free on iPhone, no account needed."):
    return f'''<div class="tintcard dl">
    <div style="flex:1;min-width:240px"><b style="color:var(--greenDeep)">{TAGLINE}</b><br>{line}</div>
    <a class="btn" href="{STORE}{token}">Get RunCalendar</a>
  </div>'''

FINE = ("Every race here is published by its organiser; RunCalendar checks the date and the entry window against the organiser's own page and rebuilds this calendar every night. "
        "A confirmed date shows its day; a provisional one shows only its month. Last updated " + TODAY.strftime("%-d %B %Y") + ".")

def collection_cards(cols, code, by_id):
    mine = [c for c in cols if c.get("countries") and code in c["countries"]]
    glob = [c for c in cols if not c.get("countries")]
    picks = (mine + glob)[:5]
    if not picks: return ""
    cards = ""
    for c in picks:
        iso_ = (c.get("countries") or [None])[0]
        mood = c["slug"][:-3] if iso_ and c["slug"].endswith("-" + iso_.lower()) else c["slug"]
        path = f"/collections/{cslug(iso_)}/{mood}/" if iso_ else f"/collections/{mood}/"
        ph = f'<img src="{esc(c["hero_image_url"])}" alt="" loading="lazy">' if c.get("hero_image_url") else '<span class="grad"></span>'
        cards += f'<a class="ccard" href="{path}"><div class="ph">{ph}</div><div class="cb"><h3>{esc(c["title"])}</h3><div class="cs">{esc(c.get("hook") or c.get("subtitle") or "")}</div></div></a>'
    return f'<div class="label">Collections{(" in " + esc(by_id["name"])) if by_id else ""}</div><div class="cards">{cards}</div>'

# ---------------------------------------------------------------- hubs
def hero_block(eyebrow, h1, sub, placeholder, index_url, img, cap):
    pic = f'<img src="{esc(img)}" alt="{esc(cap)}">' if img else '<span class="grad"></span>'
    return f'''<div class="hubhero{'' if img else ' nopic'}">
    {pic}
    <div class="hubhero-in">
      <div class="eyebrow">{eyebrow}</div>
      <h1>{esc(h1)}</h1>
      <p class="sub">{esc(sub)}</p>
      <div class="search"><input id="q" type="search" placeholder="{esc(placeholder)}" data-index="{index_url}" autocomplete="off"><div id="qout" class="qout"></div></div>
    </div>
    {f'<div class="hubhero-cap">{esc(cap)} · seen from above</div>' if img else ''}
  </div>'''

def hub_page(path, crumbs, eyebrow, h1, sub, placeholder, index_url, hero_img, hero_cap, months, regions, nearby, coming, see_all, token, cols_html, lang, noindex=False):
    mp = "".join(f'<a href="{m[1]}">{esc(m[0])}</a>' for m in months)
    rg = "".join(f'<a href="{r[1]}">{esc(r[0])}</a>' for r in regions) if regions else ""
    nb = "".join(f'<a href="{r[1]}">{esc(r[0])}</a>' for r in nearby) if nearby else ""
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": h1, "url": SITE + path}
    body = head(h1 + " | RunCalendar", sub, path, lang, ld=ld, og_image=hero_img, noindex=noindex) + f"""
<div class="wrap">
  <div class="crumbs wide">{crumbs}</div>
  {hero_block(eyebrow, h1, sub, placeholder, index_url, hero_img, hero_cap)}
  <div class="box">
    {('<div class="label">Browse by month</div><div class="pills">' + mp + '</div>') if mp else ''}
    {('<div class="label">Browse by region</div><div class="states">' + rg + '</div>') if rg else ''}
    {('<div class="label">Nearby</div><div class="pills">' + nb + '</div>') if nb else ''}
  </div>
</div>

<div class="content wide">
  {('<div class="label">Coming up <span class="r">in date order</span></div><ul class="races cols">' + coming + '</ul>') if coming else '<p class="sub">No upcoming races listed here yet.</p>'}
  {f'<div class="pills" style="margin-top:20px"><a class="on" href="{see_all[1]}">{esc(see_all[0])}</a></div>' if see_all else ''}

  {cols_html}

  {cta(token)}

  <p class="fine">{FINE}</p>
</div>
{SEARCH_JS}
""" + FOOT
    write(path, body)

def list_page(path, crumbs, eyebrow, h1, sub, rows, token, lang, back, noindex=False):
    ld = {"@context": "https://schema.org", "@type": "ItemList", "name": h1, "url": SITE + path, "numberOfItems": len(rows)}
    body = head(h1 + " | RunCalendar", sub, path, lang, ld=ld, noindex=noindex) + f"""
<div class="wrap">
  <div class="crumbs wide">{crumbs}</div>
  <div class="pagehead wide">
    <div class="eyebrow">{eyebrow}</div>
    <h1>{esc(h1)}</h1>
    <p class="sub">{esc(sub)}</p>
  </div>
</div>
<div class="content wide">
  <div class="label">{len(rows)} race{'s' if len(rows) != 1 else ''} <span class="r">in date order</span></div>
  <ul class="races cols">
{"".join(rows)}
  </ul>
  <div class="pills" style="margin-top:20px">{"".join(f'<a href="{b[1]}">{esc(b[0])}</a>' for b in back)}</div>
  {cta(token)}
  <p class="fine">{FINE}</p>
</div>
""" + FOOT
    write(path, body)

# ---------------------------------------------------------------- race page
def race_page(e, manifest, siblings, cols_for_event):
    code = iso(e); cc = cslug(code); cname = (e.get("country") or {}).get("name") or ""
    slug = e["slug"]; path = f"/race/{slug}/"
    name = ename(e); confirmed = bool(e.get("next_date_confirmed"))
    date_txt = long_date(e["next_event_date"]) if confirmed else month_year(e["next_event_date"]) + " · date to be announced"
    short_date = weekday_date(e["next_event_date"]) if confirmed else month_year(e["next_event_date"])
    img = frame(manifest, e)
    region = e.get("state_name") or ""
    rslug = slugify(region) if region else ""
    crumbs = f'<a href="/races/">Races</a><span>›</span><a href="/races/{cc}/">{esc(cname)}</a><span>›</span>' + (f'<a href="/races/{cc}/{rslug}/">{esc(region)}</a><span>›</span>' if region else "") + esc(name)
    ch = "".join(f'<span class="chip {k}">{esc(t)}</span>' for k, t in chips(e))
    ls = legs(e)
    tiles = "".join(f'<div class="tile"><b>{esc(l["title"])}</b><span>{esc(l["sub"])}</span></div>' for l in ls if l["sub"] != "timed") + \
            "".join(f'<div class="tile"><b>{esc(l["title"])}</b><span>timed</span></div>' for l in ls if l["sub"] == "timed")
    course = e.get("course_summary")
    kd = "".join(f'<li><div class="k {k}">{sym}</div><div class="w">{esc(w)}</div><div class="v {vc}">{esc(v)}</div></li>' for k, sym, w, v, vc in key_dates(e))
    trust = ('<div class="trust"><span class="dot"></span>Date confirmed with the organiser · entry window checked by RunCalendar</div>' if confirmed
             else '<div class="trust"><span class="dot n"></span>Provisional date, projected from last year — the organiser has not announced this edition yet. We show the month only.</div>')
    desc = e.get("description") or ""
    about = f'<h2>About</h2><p>{esc(desc)}</p>' if len(desc) > 60 else ""
    dist = dist_line(e)
    more = "".join(row(s, f"web-{cc}-race", manifest) for s in siblings)
    more_label = f"More races in {esc(region)}" if region else f"More races in {esc(cname)}"
    more_href = f"/races/{cc}/{rslug}/" if region else f"/races/{cc}/"
    cols_html = ""
    if cols_for_event:
        cols_html = '<div class="label">In these collections</div><div class="more">' + "".join(f'<a href="{p}">{esc(t)}</a>' for t, p in cols_for_event) + '</div>'
    meta_desc = (e.get("hook") or f"{name} in {place_short(e)}.") + f" {short_date}." + (f" {dist}." if dist else "") + " Course, key dates and the race seen from above."
    ed = edition(e)
    ld = {"@context": "https://schema.org", "@type": "SportsEvent", "name": name, "sport": "Running", "url": SITE + path,
          "startDate": e["next_event_date"], "eventStatus": "https://schema.org/EventScheduled", "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
          "description": (e.get("hook") or desc[:200] or name),
          "location": {"@type": "Place", "name": place_short(e) or cname, "address": {"@type": "PostalAddress", "addressLocality": e.get("city_name") or "", "addressRegion": region, "addressCountry": code}}}
    if e.get("name") != name: ld["alternateName"] = e["name"]
    if img: ld["image"] = img
    pc = e.get("primary_city") or {}
    if pc.get("lat") is not None: ld["location"]["geo"] = {"@type": "GeoCoordinates", "latitude": pc["lat"], "longitude": pc["lng"]}
    if e.get("website"):
        ld["organizer"] = {"@type": "Organization", "name": e["name"], "url": e["website"]}
        avail = "https://schema.org/SoldOut" if (ed.get("sold_out") or ed.get("registration_state") == "sold_out") else ("https://schema.org/InStock" if ed.get("registration_state") == "open" else None)
        if avail:
            ld["offers"] = {"@type": "Offer", "availability": avail, "url": e["website"]}
            if ed.get("registration_closes"): ld["offers"]["validThrough"] = ed["registration_closes"]
    lang = {"US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA", "IE": "en-IE", "NZ": "en-NZ", "ZA": "en-ZA"}.get(code, "en")
    body = head(f"{name} — {short_date}, {place_short(e) or cname} | RunCalendar", meta_desc, path, lang, ld=ld, og_image=img, noindex=not indexable(e)) + f"""
<div class="wrap">
  <div class="crumbs">{crumbs}</div>
  <div class="hero{'' if img else ' nopic'}">{f'<img src="{esc(img)}" alt="{esc(place_short(e) or cname)}, seen from above">' if img else '<span class="grad"></span>'}</div>
  <div class="racehead">
    <div class="when">{esc(date_txt)}</div>
    <h1>{esc(name)}</h1>
    <div class="place">{esc(place_long(e))}</div>
    {f'<div class="chips">{ch}</div>' if ch else ''}
    {f'<p class="hook">{esc(e["hook"])}</p>' if e.get("hook") else ''}
    <div class="saverow"><a class="savebtn" id="open" href="{STORE}web-{cc}-race">Save to my season</a><div class="small">Opens in RunCalendar.<br>Free on iPhone · No account needed.</div></div>
  </div>
</div>

<div class="content">
  {('<h2>Course</h2>' + (f'<p>{esc(course)}</p>' if course else '') + (f'<div class="tiles">{tiles}</div>' if tiles else '')) if (course or tiles) else ''}

  <h2>Key dates</h2>
  <ul class="dates">{kd}</ul>
  {trust}

  {about}

  {cta(f"web-{cc}-race", f"Save {esc(name)} to your season and RunCalendar reminds you the morning entries open and before they close. Free on iPhone, no account needed.")}

  {cols_html}

  {f'<div class="label">{more_label} <a class="r" href="{more_href}">All ›</a></div><ul class="races">{more}</ul>' if more else ''}

  <div class="foot">
    <div class="claim">Run this event? <a href="/claim/?event={e['id']}">Claim it on runcalendar.com</a></div>
    {f'<a class="site" href="{esc(e["website"])}" rel="nofollow noopener">Visit event website ›</a>' if e.get("website") else ''}
  </div>
  <p class="fine">A confirmed date shows its day; a provisional one shows only its month, because we won't claim a day we don't have. This page is rebuilt every night from the RunCalendar catalogue.</p>
</div>
<script>
(function(){{
  var from = new URLSearchParams(location.search).get('from');
  var store = "{STORE}" + (from ? from : "web-{cc}-race");
  var btn = document.getElementById('open'); btn.href = store;
  var deep = "runcalendar://event/{e['id']}";
  if (/iPhone|iPad|iPod/.test(navigator.userAgent)) btn.addEventListener('click', function(ev){{
    ev.preventDefault();
    var f = document.createElement('iframe'); f.style.display = 'none'; f.src = deep; document.body.appendChild(f);
    setTimeout(function(){{ if (!document.hidden) location.href = store; }}, 1200);
  }});
}})();
</script>
""" + FOOT
    write(path, body)

# ---------------------------------------------------------------- main
def main():
    os.makedirs(ROOT, exist_ok=True)
    with open(os.path.join(ROOT, "_catalogue.css"), "w") as f: f.write(open(CSS_SRC).read())
    print("fetching…", file=sys.stderr)
    events = fetch_events()
    cols = fetch_collections()
    manifest = fetch_manifest()
    print(f"{len(events)} events, {len(cols)} collections, {len(manifest)} satellite frames", file=sys.stderr)
    by_id = {e["id"]: e for e in events}
    col_paths = collections.defaultdict(list)
    for c in cols:
        iso_ = (c.get("countries") or [None])[0]
        mood = c["slug"][:-3] if iso_ and c["slug"].endswith("-" + iso_.lower()) else c["slug"]
        p = f"/collections/{cslug(iso_)}/{mood}/" if iso_ else f"/collections/{mood}/"
        for eid in c["members"]:
            if eid in by_id: col_paths[eid].append((c["title"], p))

    by_country = collections.defaultdict(list)
    for e in events:
        if iso(e): by_country[iso(e)].append(e)
    for code in by_country: by_country[code].sort(key=lambda e: (e["next_event_date"], e["id"]))
    country_name = {code: (evs[0].get("country") or {}).get("name") for code, evs in by_country.items()}
    codes = sorted(by_country, key=lambda c: (MAIN_MARKETS.index(c) if c in MAIN_MARKETS else 99, country_name[c]))

    sitemap_pages, sitemap_races = ["/races/"], []
    lang_of = lambda code: {"US": "en-US", "GB": "en-GB", "AU": "en-AU", "CA": "en-CA", "IE": "en-IE", "NZ": "en-NZ", "ZA": "en-ZA"}.get(code, "en")

    for code in codes:
        if ONLY and code not in ONLY: continue
        evs = by_country[code]; cname = country_name[code]; cc = cslug(code); lang = lang_of(code); cin = in_country(code, cname)
        listed = [e for e in evs if visible_in_lists(e)]
        token = f"web-{cc}-hub"
        # hero: owner's chosen race, else the first core race, else the first race
        hero_e = next((e for e in evs if e["slug"] == HERO.get(code)), None) or next((e for e in listed if e.get("tier") == "core" and frame(manifest, e)), None) \
                 or next((e for e in listed if frame(manifest, e)), None) or (listed[0] if listed else evs[0])
        hero_img = frame(manifest, hero_e); hero_cap = place_short(hero_e) or cname
        # search index
        idx = [[e["slug"], ename(e), place_short(e), (weekday_date(e["next_event_date"], False) if e.get("next_date_confirmed") else month_year(e["next_event_date"])), dist_line(e),
                re.sub(r"\s+", " ", (ename(e) + " " + (e.get("name") or "") + " " + (e.get("city_name") or "") + " " + (e.get("state_name") or "") + " " + (e.get("state_code") or "")).lower())] for e in listed]
        idx_path = f"/races/{cc}/search.json"
        os.makedirs(os.path.join(ROOT, "races", cc), exist_ok=True)
        with open(os.path.join(ROOT, "races", cc, "search.json"), "w") as f: json.dump(idx, f, ensure_ascii=False, separators=(",", ":"))
        # months
        months = sorted({month_key(e["next_event_date"]) for e in listed})[:14]
        month_links = [(month_label(m), f"/races/{cc}/{m}/") for m in months]
        # regions
        by_region = collections.defaultdict(list)
        for e in listed:
            if e.get("state_name"): by_region[e["state_name"]].append(e)
        regions = sorted(by_region)
        # the hub lists regions with a real calendar (3+); a one-race oddity still gets its (noindex) page but no slot in the box
        listed_regions = [r for r in regions if len(by_region[r]) >= 3]
        region_links = [(r, f"/races/{cc}/{slugify(r)}/") for r in listed_regions] if len(listed_regions) >= 2 else []
        coming = "".join(row(e, token, manifest) for e in listed[:COMING_UP])
        see_all = (f"See all {len(listed):,} races in {cin} by month ›", f"/races/{cc}/{months[0]}/") if months else None
        sub = f"{len(listed):,} upcoming races, from the big city starts to your own town's. Every date checked against the organiser. {TAGLINE}"
        cols_html = collection_cards(cols, code, {"name": cin})
        hub_page(f"/races/{cc}/", f'<a href="/races/">Races</a><span>›</span>{esc(cname)}', f"Race calendar · {esc(cname)}", f"Running races in {cin}", sub,
                 f"Search {len(listed):,} races in {cin}", idx_path, hero_img, hero_cap, month_links, region_links, None, coming, see_all, token, cols_html, lang)
        sitemap_pages.append(f"/races/{cc}/")
        # month pages
        for m in months:
            rows = [row(e, f"web-{cc}-month", manifest) for e in listed if month_key(e["next_event_date"]) == m]
            mlabel = month_label(m, True)
            list_page(f"/races/{cc}/{m}/", f'<a href="/races/">Races</a><span>›</span><a href="/races/{cc}/">{esc(cname)}</a><span>›</span>{esc(mlabel)}',
                      f"Race calendar · {esc(cname)}", f"Running races in {cin} in {mlabel}", f"{len(rows)} races across {cin} in {mlabel}. Every date checked against the organiser. {TAGLINE}",
                      rows, f"web-{cc}-month", lang, [(f"← {cname}", f"/races/{cc}/")] + [(month_label(x), f"/races/{cc}/{x}/") for x in months if x != m])
            sitemap_pages.append(f"/races/{cc}/{m}/")
        # region hubs + region months
        for r in regions:
            revs = by_region[r]; rs = slugify(r); rtoken = f"web-{cc}-region"
            rhero = next((e for e in revs if e.get("tier") == "core" and frame(manifest, e)), None) or next((e for e in revs if frame(manifest, e)), None) or revs[0]
            rmonths = sorted({month_key(e["next_event_date"]) for e in revs})[:14]
            rmonth_links = [(month_label(m), f"/races/{cc}/{rs}/{m}/") for m in rmonths]
            nearby = [(n, f"/races/{cc}/{slugify(n)}/") for n in US_ADJ.get(r, []) if n in by_region] if code == "US" else \
                     [(n, f"/races/{cc}/{slugify(n)}/") for n in regions if n != r][:12]
            rcoming = "".join(row(e, rtoken, manifest) for e in revs[:COMING_UP])
            rsee = (f"See all {len(revs):,} races in {r} by month ›", f"/races/{cc}/{rs}/{rmonths[0]}/") if rmonths else None
            rsub = f"{len(revs):,} upcoming races across {r}. Every date checked against the organiser. {TAGLINE}"
            hub_page(f"/races/{cc}/{rs}/", f'<a href="/races/">Races</a><span>›</span><a href="/races/{cc}/">{esc(cname)}</a><span>›</span>{esc(r)}',
                     f"Race calendar · {esc(r)}, {esc(cname)}", f"Running races in {r}", rsub, f"Search races in {cin}", idx_path,
                     frame(manifest, rhero), place_short(rhero) or r, rmonth_links, None, nearby, rcoming, rsee, rtoken, cols_html, lang, noindex=len(revs) < 3)
            if len(revs) >= 3: sitemap_pages.append(f"/races/{cc}/{rs}/")
            for m in rmonths:
                rows = [row(e, f"web-{cc}-region", manifest) for e in revs if month_key(e["next_event_date"]) == m]
                mlabel = month_label(m, True)
                list_page(f"/races/{cc}/{rs}/{m}/", f'<a href="/races/">Races</a><span>›</span><a href="/races/{cc}/">{esc(cname)}</a><span>›</span><a href="/races/{cc}/{rs}/">{esc(r)}</a><span>›</span>{esc(mlabel)}',
                          f"Race calendar · {esc(r)}", f"Running races in {r} in {mlabel}", f"{len(rows)} races across {r} in {mlabel}. {TAGLINE}",
                          rows, f"web-{cc}-region", lang, [(f"← {r}", f"/races/{cc}/{rs}/")] + [(month_label(x), f"/races/{cc}/{rs}/{x}/") for x in rmonths if x != m], noindex=len(rows) < 3)
                if len(rows) >= 3: sitemap_pages.append(f"/races/{cc}/{rs}/{m}/")
        # race pages
        for e in evs:
            pool = by_region.get(e.get("state_name") or "", None) or listed
            sibs = [s for s in pool if s["id"] != e["id"] and s["next_event_date"] >= e["next_event_date"]][:4] or [s for s in pool if s["id"] != e["id"]][:4]
            race_page(e, manifest, sibs, col_paths.get(e["id"]))
            if indexable(e): sitemap_races.append(f"/race/{e['slug']}/")
        print(f"{code} {cname}: {len(evs)} races, {len(regions)} regions, {len(months)} months", file=sys.stderr)

    # world hub
    if not ONLY:
        main_links = "".join(f'<a href="/races/{cslug(c)}/">{esc(country_name[c])}</a>' for c in MAIN_MARKETS if c in by_country)
        others = sorted([c for c in by_country if c not in MAIN_MARKETS], key=lambda c: country_name[c])
        other_links = "".join(f'<a href="/races/{cslug(c)}/">{esc(country_name[c])}</a>' for c in others)
        total = sum(1 for e in events if visible_in_lists(e))
        hero_e = next((e for e in by_country.get("US", []) if e["slug"] == HERO["US"]), None)
        ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": "Running races around the world", "url": SITE + "/races/"}
        body = head("Running races around the world — the RunCalendar race calendar | RunCalendar", f"{total:,} upcoming running races in {len(by_country)} countries, every date checked against the organiser. {TAGLINE}", "/races/", ld=ld, og_image=frame(manifest, hero_e) if hero_e else None) + f"""
<div class="wrap">
  <div class="crumbs wide">Races</div>
  {hero_block("Race calendar · Worldwide", "Running races around the world", f"{total:,} upcoming races in {len(by_country)} countries, from the Majors to your own town's. Every date checked against the organiser. {TAGLINE}", "Pick a country below to search its calendar", "/races/us/search.json", frame(manifest, hero_e) if hero_e else None, place_short(hero_e) if hero_e else "")}
  <div class="box">
    <div class="label">Where RunCalendar runs most</div><div class="pills">{main_links}</div>
    <div class="label">Every country</div><div class="states">{other_links}</div>
  </div>
</div>
<div class="content wide">
  {collection_cards([c for c in cols if not c.get("countries")], "", None)}
  {cta("web-world")}
  <p class="fine">{FINE}</p>
</div>
""" + FOOT
        # the world hub's search box points at the US index; the hero copy says pick a country, so the box is decorative there
        body = body.replace('<input id="q"', '<input id="q" disabled')
        write("/races/", body)

        # sitemaps: an index + chunks (≤ 10,000 URLs each keeps every file small)
        def smfile(name, urls):
            with open(os.path.join(ROOT, name), "w") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
                for u in urls: f.write(f"<url><loc>{SITE}{u}</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n")
                f.write("</urlset>\n")
        static = ["/", "/about/", "/contact/", "/add-event/", "/claim/", "/privacy/", "/terms/", "/collections/"]
        coll_pages = []
        for dirpath, _, files in os.walk(os.path.join(ROOT, "collections")):
            if "index.html" in files:
                rel = "/" + os.path.relpath(dirpath, ROOT).replace(os.sep, "/") + "/"
                if rel != "/collections/": coll_pages.append(rel)
        smfile("sitemap-pages.xml", static + sorted(coll_pages) + sitemap_pages)
        chunks = [sitemap_races[i:i + 10000] for i in range(0, len(sitemap_races), 10000)]
        names = []
        for i, ch in enumerate(chunks, 1):
            smfile(f"sitemap-races-{i}.xml", ch); names.append(f"sitemap-races-{i}.xml")
        with open(os.path.join(ROOT, "sitemap.xml"), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for n in ["sitemap-pages.xml"] + names: f.write(f"<sitemap><loc>{SITE}/{n}</loc><lastmod>{TODAY.isoformat()}</lastmod></sitemap>\n")
            f.write("</sitemapindex>\n")
        print(f"sitemap: {len(static) + len(coll_pages) + len(sitemap_pages)} pages + {len(sitemap_races)} indexable races in {len(names)} chunks", file=sys.stderr)
    print(f"wrote {len(written)} pages into {ROOT}", file=sys.stderr)

if __name__ == "__main__":
    main()
