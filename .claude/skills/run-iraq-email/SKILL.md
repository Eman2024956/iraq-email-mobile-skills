---
name: run-iraq-email
description: Extract Iraqi business emails and mobile phone numbers from OpenStreetMap and Google Maps (Places API) into CSV/JSON. Use when asked to run, get, extract, collect, export or scrape Iraqi emails, mobiles, phone numbers or business contacts/leads for a city (Baghdad, Basra, Erbil, Mosul, Najaf...) or category (restaurants, pharmacies, hotels...), from Google Maps or OpenStreetMap. ايميلات وأرقام موبايلات العراق، استخراج أرقام هواتف من خرائط كوكل
---

# run-iraq-email

A stdlib-Python CLI, `.claude/skills/run-iraq-email/driver.py`, that pulls **business**
contacts in Iraq and writes CSV (Excel-ready with Arabic) or JSON. Phones are normalised
to `+964…` and tagged `mobile` (075x Korek, 077x Asiacell, 078x/079x Zain) or `landline`.
All paths are relative to the project root (`/Users/falahgatea/iraq-email`).

| Command | Source | Gives | Needs |
|---|---|---|---|
| `pbf` | OpenStreetMap, offline Geofabrik extract | phones **and** emails | `.venv` + `data/iraq-latest.osm.pbf` |
| `osm` | OpenStreetMap, live Overpass API | phones and emails | Overpass reachable (it is **not** from this network) |
| `google` | Google Maps, official Places API (New) | phones + website, **never emails** | `GOOGLE_MAPS_API_KEY` in `.env` |
| `enrich` | each row's own website | emails published on the site | the output of another command |

## Setup (once)

```bash
mkdir -p data && curl -sL -o data/iraq-latest.osm.pbf https://download.geofabrik.de/asia/iraq-latest.osm.pbf
```

```bash
python3 -m venv .venv && .venv/bin/pip install -q osmium
```

The extract is 92 MB and Geofabrik refreshes it daily. Re-run the curl to get new data.
For Google, copy `.env.example` to `.env` and fill in `GOOGLE_MAPS_API_KEY=`.
`.env`, `.venv/`, `data/` and `out/` are listed in `.gitignore`.

## Run (agent path)

`--area` takes any Iraqi city or governorate name (looked up with Nominatim, which gives a
bounding box), or `Iraq` for the whole country. `--tag` is an OSM filter. `--only email|mobile`
keeps only rows that have one. If `--out` ends in `.json` you get JSON, otherwise CSV.

```bash
# Every business in Iraq that has a phone or email (~12.7k rows, ~2 s)
.venv/bin/python .claude/skills/run-iraq-email/driver.py pbf --area Iraq --out out/iraq_all.csv

# One city + category
.venv/bin/python .claude/skills/run-iraq-email/driver.py pbf --area Erbil --tag amenity=restaurant --out out/erbil_restaurants.csv

# Emails only
.venv/bin/python .claude/skills/run-iraq-email/driver.py pbf --area Basra --need email --only email --out out/basra_emails.csv

# Mobiles only, as JSON
.venv/bin/python .claude/skills/run-iraq-email/driver.py pbf --area Baghdad --tag amenity=pharmacy --only mobile --out out/bgd_pharmacy.json

# Find emails on the businesses' own websites (homepage + /contact, follows robots.txt)
.venv/bin/python .claude/skills/run-iraq-email/driver.py enrich out/erbil_restaurants.csv --out out/erbil_enriched.csv
```

The progress log goes to stderr and ends with
`[done] N rows (M mobile, K with email) -> path`. Check that line.
Useful tags: `amenity=restaurant|cafe|pharmacy|clinic|hospital|school|bank`, `shop` (any shop),
`shop=supermarket`, `office` (any office), `tourism=hotel`, `healthcare`.

Columns: `source,name,category,city,address,phone,phone_type,all_phones,email,website,lat,lon,source_id`

### Google Maps (Places API) — NOT YET TESTED in this project

```
.venv/bin/python .claude/skills/run-iraq-email/driver.py google --query "pharmacies in Basra" --pages 3 --out out/basra_google.csv
```

You get at most 60 results per query (3 pages of 20), so split by district or category.
Google never returns emails. Run `enrich` on the output to get them from websites.
Google bills each request. With no key, the command exits with
`[google] put GOOGLE_MAPS_API_KEY=... in ./.env`.

## Gotchas

- **Overpass is unreachable from this machine.** Every mirror tested on 2026-11-24 failed:
  overpass-api.de and kumi.systems timed out on connect, maps.mail.ru returned 504,
  private.coffee's `/status` answered but its queries hung. That is why `pbf` (offline)
  is the main path. `osm` tries 4 mirrors in turn. To pin one, set `OVERPASS_URL=...`.
- **Do not scrape the Google Maps website.** It breaks Google's terms and runs into bot
  checks. Use the Places API (`google`) only.
- **The Nominatim bbox is a rectangle**, so it can catch some places just outside the city.
  "Baghdad" resolves to the Green Zone municipality relation, whose bbox still covers the
  main city. To use exact limits, filter the CSV on `lat/lon`.
- **`city` comes from the OSM `addr:city` tag** when the place has one, so it can be in
  Arabic or Kurdish even when you passed `--area Erbil`.
- The CSV has a UTF-8 BOM so Excel shows Arabic and Kurdish correctly. JSON has no BOM.
- `enrich` skips Facebook, Instagram, t.me, wa.me and linktree URLs. Many Iraqi businesses
  list only a Facebook page, so expect few hits: 1 in 4 on the Erbil sample.
- Some numbers are entered badly in OSM. The normaliser handles `07xx…`, `+964…`, `00964…`
  and bare `7xxxxxxxxx`. Anything else comes out with `phone_type=other`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `URLError: [Errno 60] Operation timed out` on `osm` | Overpass is blocked or down. Use `pbf`. |
| `HTTP Error 504: Gateway Time-out` on `osm` | That mirror is overloaded. The driver moves to the next one. |
| `[pbf] needs osmium` | You ran system `python3`. Use `.venv/bin/python`. |
| `AttributeError: module 'osmium' has no attribute '__version__'` | Harmless: osmium has no `__version__`. The install is fine. |
| `[pbf] Nominatim found no place called ...` | Use the English or Arabic name (e.g. `Najaf`, `النجف`). |

## Use responsibly

This is business-listing data (OSM is ODbL: credit "© OpenStreetMap contributors").
Before sending bulk email or SMS, follow anti-spam rules: identify yourself and include an
opt-out. Don't build lists of private individuals.
