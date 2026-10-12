# Burn2Earn / Regenerix Core Platform

Master-data platform for the biomass infrastructure network. This repo holds **build
step 1 (Foundation)** of the V1 data model and build plan.

## What step 1 includes

| Area | What it does |
| --- | --- |
| `apps/accounts` | Login accounts with four roles: Admin, Biomass Mitra, Farmer, Buyer. Only Admin and Mitra accounts are used in V1. |
| `apps/core` | Shared base model (UUID id, status, created/updated by and at), a change log (audit log) for every master record, and acre-based area maths. Records are deactivated, never deleted. |
| `apps/geography` | State > District > Block > Panchayat > Village from LGD codes, loaded with management commands. |
| `apps/territory` | **Region** and **GeoCell**. In V1 each GeoCell is one panchayat. A database trigger stops two active GeoCells from overlapping (sharing an edge is fine). |

Not in step 1 yet: Grid, Mitra profile, Equipment, Hub, Farmer, Farm Plot, Buyer,
Factory, reference masters (Crop, Season, Biomass Type...), the REST API and the Mitra
field app. These are build steps 2 to 5.

**Areas are in acres everywhere** (`area_acres`). They are calculated from the boundary
on every save and cannot be edited by hand.

## Run it with Docker

```bash
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

Open http://localhost:8000/admin/ and log in. Superusers get the Admin role automatically.

## Run it without Docker

You need Python 3.12+, PostgreSQL 16 with PostGIS, and the GDAL, GEOS and PROJ libraries
(macOS: `brew install postgresql postgis gdal`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then export the variables, or set them in your shell
createdb burn2earn
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Load data

```bash
# 1. Geography from a flat CSV (columns: see apps/geography/management/commands/load_geography.py)
python manage.py load_geography path/to/lgd.csv

# 2. Panchayat boundaries from GeoJSON (lon/lat), matched on an LGD code property
python manage.py load_panchayat_boundaries path/to/panchayats.geojson --code-property lgd_code

# 3. In the admin, create a Region, then pick it and run the action
#    "Generate one GeoCell per panchayat". Or from the command line:
python manage.py generate_geocells REG-HR-AMB-001
```

Both loaders and the generator are safe to re-run.

## Tests

```bash
python manage.py test
```

GitHub Actions runs the Django checks, a migrations check and the full test suite against
PostGIS on every push (`.github/workflows/ci.yml`).

## Design notes

- **One source of truth for links.** The GeoCell will store its Grid, and the Grid will
  store its Hub; the Mitra link will be an effective-dated assignment record. Everything
  else is derived. These arrive with the Grid model in step 2.
- **GeoCell boundary is a MultiPolygon**, not a Polygon as the spec says, because a
  panchayat boundary can have several parts.
- **Who changed what.** `CurrentUserMiddleware` records the logged-in user on every web
  request. Scripts and the future API must call `set_current_user(...)` themselves.
- **Bulk loads write one audit row per record**, so a very large village import is slow.
  If that becomes a problem, the loaders can be changed to skip unchanged rows.
