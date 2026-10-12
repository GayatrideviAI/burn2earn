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
| `apps/network` | **Hub** (run by Regenerix staff, fed by many Grids), **Biomass Grid**, **Biomass Mitra** and **Equipment**. A GeoCell is linked to its Grid from the GeoCell list in the admin. The Grid warns when it has fewer than 7 or more than 10 cells, and its catchment area is derived from its cells. A Mitra runs one Grid at a time through a dated assignment, and their cells and equipment come from that Grid. Equipment sits at exactly one Grid or Hub, and its types (Pelletizer, Baler...) are an editable list. |

| `apps/reference` | Editable lists: **Crop** (Paddy, Wheat, ...) and **Season** (Kharif, Rabi). The starting values are indicative; Admins can change them. |
| `apps/farms` | **Farmer** (registered by a Mitra, with a consent record captured at the same time), **Farm Plot** (a point or boundary, area in acres, placed in a GeoCell automatically) and **Plot Season** (which crop was grown in which season and year). Withdrawing consent anonymises the farmer (name and mobile removed); plots and history stay. Names and mobile numbers are never written to the change log. |

Not built yet: Buyer, Factory, the other reference masters (Biomass Type...), the REST API
and the offline Mitra app.

## The Mitra web page

Log in at `/mitra/` with a Mitra's own account (Accounts > Users, role Biomass Mitra, linked
to the Mitra record). A Mitra can register a farmer (consent tickbox required, duplicate mobile
numbers are flagged), add plots (latitude and longitude, or "Use my location" on a phone, and the
area in acres) and record crops per season. A Mitra sees only farmers they registered or who farm
in their Grid's cells. It needs an internet connection; the offline version comes later.

## Registering farmers (admin)

Farmers can be added under Farms > Farmers (a consent record is required) and plots under
Farms > Farm plots. A plot that falls outside every GeoCell is kept and can be found with
the "Outside every GeoCell" filter. The notice wording (`draft-1`) is a placeholder and needs
review before real use.

## Setting up a Mitra and their equipment (in the admin)

1. Create the Hub and the Grid (Network > Hubs, Grids). Add equipment on the Grid's own page.
2. Assign GeoCells to the Grid from Territory > GeoCells (pick the Grid in the list).
3. Create a login for the Mitra (Accounts > Users, role Biomass Mitra), then create the Mitra
   (Network > Mitras) and link that login.
4. On the Mitra's page, add a Grid assignment with a start date and no end date.
5. To change a Grid's Mitra later: set an end date on the old assignment, then add a new one.
   The old one stays as history.

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

- **One source of truth for links.** The GeoCell stores its Grid and the Grid stores its
  Hub; the Mitra link will be a dated assignment record. Everything else (a Grid's cells,
  its catchment, a Mitra's cells) is derived. When a cell moves to another Grid, the audit
  log keeps who moved it, when, and from where.
- **GeoCell boundary is a MultiPolygon**, not a Polygon as the spec says, because a
  panchayat boundary can have several parts.
- **Who changed what.** `CurrentUserMiddleware` records the logged-in user on every web
  request. Scripts and the future API must call `set_current_user(...)` themselves.
- **Bulk loads write one audit row per record**, so a very large village import is slow.
  If that becomes a problem, the loaders can be changed to skip unchanged rows.
