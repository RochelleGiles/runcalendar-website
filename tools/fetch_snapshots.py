#!/usr/bin/env python3
"""Fetch one Apple Maps satellite frame per race for runcalendar.com and keep it in our own bucket.

    python3 Tools/website/fetch_snapshots.py [--limit N] [--only US,GB] [--dry]

Reads:  ~/Documents/RunCalendarSecrets/maps.env   (KEY_ID, TEAM_ID, P8=<path to the .p8>, SUPABASE_SECRET=<service key>)
Writes: web-assets/sat/<event_id>.jpg in Supabase Storage (public bucket) + web-assets/sat/manifest.json
        {event_id: public url} — the manifest is what build_catalogue.py reads, so a race without a frame
        simply keeps the brand gradient until the next run.

Frame rule (the app's SceneMap, kept on purpose so the web and the phone show the same place):
latitude span 0.045, satellite imagery, light, no points of interest. Apple's mark is baked into the
bottom-left of every frame and the pages keep it visible (object-position bottom / left-bottom).
A frame that is nearly black (open water, no imagery) is NOT kept — gradient instead, like the app.
A fetch failure is never recorded, so the next run retries it.

Apple Maps Web Snapshots: the request path + query (ending in teamId & keyId) is signed ES256 with the
Maps key and the base64url signature is appended as &signature=. Daily allowance is 25,000 snapshots per
Apple Developer membership, so the first full pass runs over two days (--limit).
"""
import json, os, sys, math, base64, subprocess, tempfile, urllib.request, urllib.parse, datetime, time

REST = "https://rteqvslwxgsgvccrgtzg.supabase.co/rest/v1"
STORAGE = "https://rteqvslwxgsgvccrgtzg.supabase.co/storage/v1"
PUBLIC = STORAGE + "/object/public/web-assets/sat/"
ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ0ZXF2c2x3eGdzZ3ZjY3JndHpnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDM2NDExOTUsImV4cCI6MjA1OTIxNzE5NX0.9nS2ATC2p2bfruWNhKylrIPamtYfnb6hTSyv5GC5Ksw"
SNAP = "https://snapshot.apple-mapkit.com"
SIZE = (640, 400)          # points; scale 2 → 1280×800 px, the largest the API allows at this aspect
LAT_SPAN = 0.045           # the app's fixed span
TODAY = datetime.date.today()

args = sys.argv[1:]
LIMIT = int(args[args.index("--limit") + 1]) if "--limit" in args else 24000
ONLY = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
DRY = "--dry" in args
SHARD = tuple(int(x) for x in args[args.index("--shard") + 1].split("/")) if "--shard" in args else (0, 1)   # k/n: every nth race

def load_env():
    p = os.path.expanduser("~/Documents/RunCalendarSecrets/maps.env")
    env = {}
    for line in open(p):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"')
    for k in ("KEY_ID", "TEAM_ID", "P8", "SUPABASE_SECRET"):
        if k not in env: sys.exit(f"maps.env is missing {k}")
    env["P8"] = os.path.expanduser(env["P8"])
    return env

def der_to_raw(der):
    # ECDSA DER SEQUENCE { INTEGER r, INTEGER s } → 64-byte r||s (JOSE / Apple's expected form)
    assert der[0] == 0x30
    i = 2 if der[1] < 0x80 else 2 + (der[1] & 0x7F)
    assert der[i] == 0x02; rl = der[i + 1]; r = der[i + 2:i + 2 + rl]; i = i + 2 + rl
    assert der[i] == 0x02; sl = der[i + 1]; s = der[i + 2:i + 2 + sl]
    r = r.lstrip(b"\x00").rjust(32, b"\x00"); s = s.lstrip(b"\x00").rjust(32, b"\x00")
    return r + s

def sign(path_and_query, p8):
    with tempfile.NamedTemporaryFile(delete=False) as f: f.write(path_and_query.encode()); tmp = f.name
    try:
        der = subprocess.check_output(["openssl", "dgst", "-sha256", "-sign", p8, tmp])
    finally: os.unlink(tmp)
    return base64.urlsafe_b64encode(der_to_raw(der)).decode().rstrip("=")

def snapshot_url(lat, lng, env):
    lng_span = LAT_SPAN * (SIZE[0] / SIZE[1]) / max(math.cos(math.radians(lat)), 0.2)
    q = urllib.parse.urlencode({"center": f"{lat:.5f},{lng:.5f}", "spn": f"{LAT_SPAN},{lng_span:.5f}", "size": f"{SIZE[0]}x{SIZE[1]}",
                                "scale": "2", "t": "satellite", "poi": "0", "colorScheme": "light", "lang": "en-US",
                                "teamId": env["TEAM_ID"], "keyId": env["KEY_ID"]})
    path = "/api/v1/snapshot?" + q
    return SNAP + path + "&signature=" + sign(path, env["P8"])

def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=60).read()

def process(raw):
    """Apple's snapshot arrives as a ~1.8 MB PNG. Returns (progressive JPEG bytes ~200 KB, mean luminance 0..1)."""
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    lum = sum(im.convert("L").resize((16, 16)).getdata()) / (256 * 255)
    out = io.BytesIO(); im.save(out, "JPEG", quality=78, optimize=True, progressive=True)
    return out.getvalue(), lum

def list_objects(secret):
    """Every sat/<id>.jpg held in the bucket, via the storage list API (service key)."""
    names, off = [], 0
    while True:
        body = json.dumps({"prefix": "sat/", "limit": 1000, "offset": off, "sortBy": {"column": "name", "order": "asc"}}).encode()
        req = urllib.request.Request(STORAGE + "/object/list/web-assets", data=body, method="POST",
                                     headers={"Authorization": "Bearer " + secret, "apikey": secret, "Content-Type": "application/json"})
        chunk = json.loads(urllib.request.urlopen(req, timeout=120).read())
        names += [o["name"].split("/")[-1] for o in chunk if o.get("name", "").endswith(".jpg")]
        if len(chunk) < 1000: return names
        off += 1000

def save_manifest(new_entries, secret):
    # several fetchers may run side by side: merge into the live manifest, never overwrite it
    try: live = read_manifest()
    except Exception: live = {}
    live.update(new_entries)
    upload("sat/manifest.json", json.dumps(sorted(live), separators=(",", ":")).encode(), "application/json", secret)
    return live

def read_manifest():
    """The manifest is a JSON LIST of event ids (a dict of urls grew past the bucket's 2 MB limit)."""
    raw = json.loads(get(PUBLIC + "manifest.json?t=" + str(time.time())))
    return {i: PUBLIC + i + ".jpg" for i in raw} if isinstance(raw, list) else raw

def upload(path, data, ctype, secret):
    req = urllib.request.Request(STORAGE + "/object/web-assets/" + path, data=data, method="POST",
                                 headers={"Authorization": "Bearer " + secret, "apikey": secret, "Content-Type": ctype, "x-upsert": "true"})
    urllib.request.urlopen(req, timeout=120).read()

def rebuild_manifest(env):
    names = list_objects(env["SUPABASE_SECRET"])
    manifest = {n[:-4]: PUBLIC + n for n in names if n != "manifest.json"}
    upload("sat/manifest.json", json.dumps(sorted(manifest), separators=(",", ":")).encode(), "application/json", env["SUPABASE_SECRET"])
    print(f"manifest rebuilt from the bucket: {len(manifest)} frames", file=sys.stderr)
    return manifest

def recompress(env):
    names = [n for n in list_objects(env["SUPABASE_SECRET"]) if n != "manifest.json"]
    names = [n for i, n in enumerate(names) if i % SHARD[1] == SHARD[0]]
    print(f"recompressing {len(names)} held frames in this shard", file=sys.stderr)
    done = 0
    for n in names:
        try:
            raw = get(PUBLIC + n + "?t=" + str(time.time()))
            if raw[:4] != b"\x89PNG": continue               # already a JPEG
            jpeg, _ = process(raw)
            upload("sat/" + n, jpeg, "image/jpeg", env["SUPABASE_SECRET"]); done += 1
            if done % 100 == 0: print(f"  {done} recompressed", file=sys.stderr)
        except Exception as ex:
            print(f"  {n}: {ex}", file=sys.stderr)
    print(f"finished: {done} recompressed", file=sys.stderr)

def main():
    env = load_env()
    if "--rebuild-manifest" in args: rebuild_manifest(env); return
    if "--recompress" in args: recompress(env); return
    try: manifest = read_manifest()
    except Exception: manifest = {}
    print(f"{len(manifest)} frames already held", file=sys.stderr)
    # every upcoming visible race with a pin, biggest markets first so the first day covers them
    events, off = [], 0
    while True:
        chunk = json.loads(get(REST + f"/events?select=id,slug,tier,next_event_date,country:countries!country_id(iso_code),primary_city:cities!primary_city_id(lat,lng)"
                                      f"&status=eq.published&or=(tier.eq.core,tier.eq.local,tier.is.null)&next_event_date=gte.{TODAY.isoformat()}&order=id&limit=1000&offset={off}",
                               {"apikey": ANON, "Authorization": "Bearer " + ANON}))
        events += chunk
        if len(chunk) < 1000: break
        off += 1000
    order = {"US": 0, "GB": 1, "AU": 2, "ZA": 3, "CA": 4, "IE": 5, "NZ": 6}
    todo = [e for e in events if e["id"] not in manifest and (e.get("primary_city") or {}).get("lat") is not None
            and (not ONLY or (e.get("country") or {}).get("iso_code") in ONLY)]
    todo.sort(key=lambda e: (order.get((e.get("country") or {}).get("iso_code"), 9), 0 if e.get("tier") == "core" else 1, e["next_event_date"]))
    todo = [e for i, e in enumerate(todo) if i % SHARD[1] == SHARD[0]]
    print(f"{len(todo)} races need a frame in this shard; fetching up to {LIMIT}", file=sys.stderr)
    done = fails = dark = 0; new = {}
    for e in todo[:LIMIT]:
        pc = e["primary_city"]; url = snapshot_url(pc["lat"], pc["lng"], env)
        if DRY: print(url); continue
        try:
            jpeg = get(url)
        except urllib.error.HTTPError as ex:
            fails += 1; print(f"  {e['slug']}: HTTP {ex.code}", file=sys.stderr)
            if ex.code == 429: print("daily allowance reached — stop here, run again tomorrow", file=sys.stderr); break
            continue
        except Exception as ex:
            fails += 1; print(f"  {e['slug']}: {ex}", file=sys.stderr); continue
        jpeg, lum = process(jpeg)
        if lum < 0.06:
            dark += 1; continue          # no picture here (open water) — never cached, like the app
        try:
            upload(f"sat/{e['id']}.jpg", jpeg, "image/jpeg", env["SUPABASE_SECRET"])
        except Exception as ex:
            fails += 1; print(f"  upload {e['slug']}: {ex}", file=sys.stderr); continue
        new[e["id"]] = PUBLIC + f"{e['id']}.jpg"; done += 1
        if done % 100 == 0:
            save_manifest(new, env["SUPABASE_SECRET"]); new = {}
            print(f"  {done} done, {fails} failed, {dark} dark", file=sys.stderr)
    if not DRY and new:
        manifest = save_manifest(new, env["SUPABASE_SECRET"])
    print(f"finished: {done} new frames, {fails} failed, {dark} dark; manifest holds {len(manifest)}", file=sys.stderr)

if __name__ == "__main__":
    main()
