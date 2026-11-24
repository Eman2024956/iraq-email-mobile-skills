#!/usr/bin/env python3
"""Iraqi business-contact extractor (stdlib only, no pip install).

Sources:
  osm     - OpenStreetMap via the public Overpass API (no key, ODbL data).
  google  - Google Maps via the official Places API (New) Text Search.
            Needs GOOGLE_MAPS_API_KEY. Google returns phones + website, never emails.
  enrich  - Visit each row's own website (homepage + /contact) and pull
            published mailto/email addresses. Respects robots.txt.

All commands write CSV (default) or JSON. Phones are normalised to +964 and
tagged mobile (07xx carriers) or landline.

Examples:
  python3 driver.py osm --area Baghdad --tag amenity=restaurant --out out/bgd.csv
  python3 driver.py google --query "hotels in Erbil" --out out/erbil.csv
  python3 driver.py enrich out/erbil.csv --out out/erbil_emails.csv
"""
import argparse, csv, json, os, re, sys, time, urllib.parse, urllib.request, urllib.robotparser

UA = "iraq-contacts-skill/1.0 (business-directory research)"
# Mirrors tried in order; first that answers wins. overpass-api.de times out
# from some networks, so it is not first. Override with OVERPASS_URL.
OVERPASS_MIRRORS = ([os.environ["OVERPASS_URL"]] if os.environ.get("OVERPASS_URL") else [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
])
PLACES = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ["source", "name", "category", "city", "address", "phone", "phone_type",
          "all_phones", "email", "website", "lat", "lon", "source_id"]

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BAD_EMAIL_END = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
# Iraqi mobile prefixes: 075x Korek, 077x Asiacell, 078x/079x Zain, 076x Omnnea
MOBILE_PREFIX = ("75", "76", "77", "78", "79")


# ---------------------------------------------------------------- phones
def norm_phone(raw):
    """Return (+964..., 'mobile'|'landline'|'other') or (None, None)."""
    d = re.sub(r"[^\d+]", "", raw or "")
    if d.startswith("+"):
        d = d[1:]
    elif d.startswith("00"):
        d = d[2:]
    if d.startswith("964"):
        nat = d[3:]
    elif d.startswith("0"):
        nat = d[1:]
    elif len(d) == 10 and d.startswith("7"):
        nat = d
    else:
        return ("+" + d if d else None), ("other" if d else None)
    nat = nat.lstrip("0")
    if len(nat) == 10 and nat[:2] in MOBILE_PREFIX:
        return "+964" + nat, "mobile"
    if 7 <= len(nat) <= 9:
        return "+964" + nat, "landline"
    return "+964" + nat, "other"


def pick_phones(raws):
    out, seen = [], set()
    for r in raws:
        for part in re.split(r"[;,/|]", r or ""):
            p, t = norm_phone(part)
            if p and p not in seen:
                seen.add(p)
                out.append((p, t))
    out.sort(key=lambda x: x[1] != "mobile")  # mobiles first
    return out


def row_from(source, name, cat, city, addr, phones_raw, emails, website, lat, lon, sid):
    phones = pick_phones(phones_raw)
    return {
        "source": source, "name": name or "", "category": cat or "", "city": city or "",
        "address": addr or "", "phone": phones[0][0] if phones else "",
        "phone_type": phones[0][1] if phones else "",
        "all_phones": ";".join(p for p, _ in phones),
        "email": ";".join(dict.fromkeys(e.strip().lower() for e in emails if e and e.strip())),
        "website": website or "", "lat": lat or "", "lon": lon or "", "source_id": sid,
    }


# ---------------------------------------------------------------- http
def http(url, data=None, headers=None, timeout=180):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


# ---------------------------------------------------------------- OSM
def osm(args):
    if args.area.lower() in ("iraq", "iq", "all"):
        area = 'area["ISO3166-1"="IQ"][admin_level=2]->.a;'
    else:
        a = args.area.replace('"', "")
        area = (f'area["boundary"="administrative"]["name:en"="{a}"]->.a1;'
                f'area["boundary"="administrative"]["name"="{a}"]->.a2;'
                f'(.a1;.a2;)->.a;')
    tag = ""
    if args.tag:
        k, _, v = args.tag.partition("=")
        tag = f'["{k}"="{v}"]' if v else f'["{k}"]'
    contact_keys = ["phone", "contact:phone", "mobile", "contact:mobile",
                    "email", "contact:email"]
    if args.need == "email":
        contact_keys = ["email", "contact:email"]
    elif args.need == "phone":
        contact_keys = ["phone", "contact:phone", "mobile", "contact:mobile"]
    parts = "".join(f'nwr{tag}["{k}"](area.a);' for k in contact_keys)
    q = f'[out:json][timeout:{args.timeout}];{area}({parts});out center tags {args.limit};'
    print(f"[osm] querying Overpass for area={args.area!r} tag={args.tag!r} ...", file=sys.stderr)
    body = urllib.parse.urlencode({"data": q}).encode()
    data, last = None, None
    for url in OVERPASS_MIRRORS:
        try:
            print(f"[osm]   mirror {url}", file=sys.stderr)
            data = json.loads(http(url, data=body, timeout=args.timeout + 30))
            break
        except Exception as ex:  # timeout, 429, 504, bad JSON -> next mirror
            last = ex
            print(f"[osm]   failed: {ex}", file=sys.stderr)
    if data is None:
        sys.exit(f"[osm] all Overpass mirrors failed: {last}")
    if data.get("remark"):
        print(f"[osm] server remark: {data['remark']}", file=sys.stderr)
    rows = []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        cat = next((f"{k}={t[k]}" for k in ("amenity", "shop", "office", "tourism",
                    "healthcare", "craft", "leisure") if k in t), "")
        addr = " ".join(t.get(k, "") for k in ("addr:street", "addr:housenumber",
                         "addr:district")).strip()
        rows.append(row_from(
            "osm", t.get("name:en") or t.get("name") or t.get("name:ar"), cat,
            t.get("addr:city", ""), addr,
            [t.get(k) for k in ("contact:mobile", "mobile", "phone", "contact:phone")],
            [t.get("email"), t.get("contact:email")],
            t.get("website") or t.get("contact:website"), lat, lon,
            f"{el['type']}/{el['id']}"))
    return rows


# ---------------------------------------------------------------- OSM offline (.pbf)
def area_bbox(area):
    """City/governorate name -> (south, west, north, east) via Nominatim."""
    if not area or area.lower() in ("iraq", "iq", "all"):
        return None
    q = urllib.parse.urlencode({"q": area, "countrycodes": "iq", "format": "json", "limit": 1})
    res = json.loads(http("https://nominatim.openstreetmap.org/search?" + q, timeout=30))
    if not res:
        sys.exit(f"[pbf] Nominatim found no place called {area!r} in Iraq")
    s, n, w, e = map(float, res[0]["boundingbox"])
    print(f"[pbf] {area} -> {res[0]['display_name'][:70]} bbox=({s},{w},{n},{e})", file=sys.stderr)
    return s, w, n, e


def pbf(args):
    try:
        import osmium
    except ImportError:
        sys.exit("[pbf] needs osmium: run with .venv/bin/python (see SKILL.md)")
    if not os.path.exists(args.file):
        sys.exit(f"[pbf] {args.file} missing - download it first (see SKILL.md)")
    bbox = area_bbox(args.area)
    keys = {"any": ("phone", "contact:phone", "mobile", "contact:mobile", "email", "contact:email"),
            "email": ("email", "contact:email"),
            "phone": ("phone", "contact:phone", "mobile", "contact:mobile")}[args.need]
    tk, _, tv = (args.tag or "").partition("=")
    rows = []
    fp = osmium.FileProcessor(args.file).with_locations().with_filter(osmium.filter.KeyFilter(*keys))
    for o in fp:
        if o.is_relation():
            continue
        t = dict(o.tags)
        if tk and (tk not in t or (tv and t[tk] != tv)):
            continue
        if o.is_node():
            lat, lon = o.location.lat, o.location.lon
        else:
            pts = [n.location for n in o.nodes if n.location.valid()]
            if not pts:
                continue
            lat = sum(p.lat for p in pts) / len(pts)
            lon = sum(p.lon for p in pts) / len(pts)
        if bbox and not (bbox[0] <= lat <= bbox[2] and bbox[1] <= lon <= bbox[3]):
            continue
        cat = next((f"{k}={t[k]}" for k in ("amenity", "shop", "office", "tourism",
                    "healthcare", "craft", "leisure") if k in t), "")
        addr = " ".join(t.get(k, "") for k in ("addr:street", "addr:housenumber",
                         "addr:district")).strip()
        rows.append(row_from(
            "osm", t.get("name:en") or t.get("name") or t.get("name:ar"), cat,
            t.get("addr:city", args.area if bbox else ""), addr,
            [t.get(k) for k in ("contact:mobile", "mobile", "phone", "contact:phone")],
            [t.get("email"), t.get("contact:email")],
            t.get("website") or t.get("contact:website"), round(lat, 6), round(lon, 6),
            f"{'node' if o.is_node() else 'way'}/{o.id}"))
        if len(rows) >= args.limit:
            break
    return rows


# ---------------------------------------------------------------- Google
def load_dotenv():
    for p in (".env", os.path.join(os.path.dirname(__file__), ".env")):
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                k, sep, v = line.strip().partition("=")
                if sep and not k.startswith("#"):
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def google(args):
    load_dotenv()
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        sys.exit("[google] put GOOGLE_MAPS_API_KEY=... in ./.env (Places API (New) enabled)")
    mask = ",".join(["places.id", "places.displayName", "places.formattedAddress",
                     "places.nationalPhoneNumber", "places.internationalPhoneNumber",
                     "places.websiteUri", "places.location", "places.primaryType",
                     "nextPageToken"])
    rows, token, page = [], None, 0
    while page < args.pages:
        body = {"textQuery": args.query, "regionCode": "IQ",
                "languageCode": args.lang, "pageSize": 20}
        if token:
            body["pageToken"] = token
        print(f"[google] page {page + 1} for {args.query!r}", file=sys.stderr)
        res = json.loads(http(PLACES, data=json.dumps(body).encode(), headers={
            "Content-Type": "application/json", "X-Goog-Api-Key": key,
            "X-Goog-FieldMask": mask}, timeout=60))
        for p in res.get("places", []):
            loc = p.get("location", {})
            rows.append(row_from(
                "google", p.get("displayName", {}).get("text"), p.get("primaryType"),
                "", p.get("formattedAddress"),
                [p.get("internationalPhoneNumber"), p.get("nationalPhoneNumber")],
                [], p.get("websiteUri"), loc.get("latitude"), loc.get("longitude"),
                p.get("id")))
        token = res.get("nextPageToken")
        page += 1
        if not token:
            break
        time.sleep(2)
    return rows


# ---------------------------------------------------------------- enrich
def site_emails(url, timeout):
    if not url.startswith("http"):
        url = "http://" + url
    base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(url))
    rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
    try:
        rp.read()
    except Exception:
        rp = None
    found = []
    for u in (url, base + "/contact", base + "/contact-us", base + "/ar/contact"):
        if rp and not rp.can_fetch(UA, u):
            continue
        try:
            html = http(u, timeout=timeout)
        except Exception:
            continue
        for e in EMAIL_RE.findall(html):
            e = e.lower().rstrip(".")
            if not e.endswith(BAD_EMAIL_END) and "example" not in e and e not in found:
                found.append(e)
        if found:
            break
        time.sleep(0.5)
    return found


def enrich(args):
    with open(args.infile, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for i, r in enumerate(rows):
        social = re.search(r"facebook|instagram|fb\.com|t\.me|wa\.me|linktr", r.get("website", ""))
        if r.get("website") and not r.get("email") and not social:
            em = site_emails(r["website"], args.timeout)
            if em:
                r["email"] = ";".join(em)
                if r.get("source") and "+web" not in r["source"]:
                    r["source"] += "+web"
            print(f"[enrich] {i + 1}/{len(rows)} {r['website']} -> {em or '-'}", file=sys.stderr)
    return rows


# ---------------------------------------------------------------- output
def write(rows, args):
    if getattr(args, "only", None) == "email":
        rows = [r for r in rows if r.get("email")]
    elif getattr(args, "only", None) == "mobile":
        rows = [r for r in rows if "mobile" in r.get("phone_type", "")]
    seen, uniq = set(), []
    for r in rows:
        k = (r.get("name", "").lower(), r.get("phone") or r.get("email"))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    is_json = (args.out or "").endswith(".json")
    enc = "utf-8" if is_json else "utf-8-sig"  # BOM so Excel shows Arabic in CSV
    f = open(args.out, "w", newline="", encoding=enc) if args.out else sys.stdout
    if is_json:
        json.dump(uniq, f, ensure_ascii=False, indent=2)
    else:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(uniq)
    if args.out:
        f.close()
    n_e = sum(1 for r in uniq if r.get("email"))
    n_m = sum(1 for r in uniq if r.get("phone_type") == "mobile")
    print(f"[done] {len(uniq)} rows ({n_m} mobile, {n_e} with email) -> {args.out or 'stdout'}",
          file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", help="output .csv or .json (default: CSV to stdout)")
    common.add_argument("--only", choices=["email", "mobile"], help="keep only rows with this")

    o = sub.add_parser("osm", parents=[common], help="OpenStreetMap / Overpass")
    o.add_argument("--area", default="Baghdad", help="city/governorate name, or 'Iraq'")
    o.add_argument("--tag", help="OSM filter, e.g. amenity=restaurant, shop, office=company")
    o.add_argument("--need", choices=["any", "email", "phone"], default="any")
    o.add_argument("--limit", type=int, default=2000)
    o.add_argument("--timeout", type=int, default=120)

    b = sub.add_parser("pbf", parents=[common], help="OpenStreetMap offline from Geofabrik .pbf")
    b.add_argument("--file", default="data/iraq-latest.osm.pbf")
    b.add_argument("--area", default="Iraq", help="city/governorate name (Nominatim bbox) or 'Iraq'")
    b.add_argument("--tag", help="OSM filter, e.g. amenity=restaurant, shop, office")
    b.add_argument("--need", choices=["any", "email", "phone"], default="any")
    b.add_argument("--limit", type=int, default=100000)

    g = sub.add_parser("google", parents=[common], help="Google Places API (New)")
    g.add_argument("--query", required=True, help='e.g. "pharmacies in Basra"')
    g.add_argument("--pages", type=int, default=3, help="20 results/page, max 3 (60)")
    g.add_argument("--lang", default="en")

    e = sub.add_parser("enrich", parents=[common], help="find emails on rows' own websites")
    e.add_argument("infile")
    e.add_argument("--timeout", type=int, default=15)

    args = ap.parse_args()
    rows = {"osm": osm, "pbf": pbf, "google": google, "enrich": enrich}[args.cmd](args)
    write(rows, args)


if __name__ == "__main__":
    main()
