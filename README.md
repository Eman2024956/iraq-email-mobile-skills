# iraq-email-mobile-skills

A Claude Code skill (`/run-iraq-email`) that pulls Iraqi **business** emails and mobile numbers
from OpenStreetMap, with a Google Maps Places API command as well, and writes CSV or JSON.
Numbers come out as `+964…` and are marked mobile or landline.

Full instructions: [.claude/skills/run-iraq-email/SKILL.md](.claude/skills/run-iraq-email/SKILL.md)

## Quick start

```bash
mkdir -p data && curl -sL -o data/iraq-latest.osm.pbf https://download.geofabrik.de/asia/iraq-latest.osm.pbf
python3 -m venv .venv && .venv/bin/pip install -q osmium
.venv/bin/python .claude/skills/run-iraq-email/driver.py pbf --area Baghdad --tag amenity=pharmacy --out out/bgd_pharmacy.csv
```

The Google command (`google`) needs `GOOGLE_MAPS_API_KEY` in `.env` (see `.env.example`).
It has not been tested yet.

Data © OpenStreetMap contributors (ODbL). Use it for business outreach only, and include an opt-out.
