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

## Try it with demo data

```bash
docker compose exec web python manage.py load_demo_data
```

Creates three made-up networks: Ambala in Haryana (8 panchayats), Kanchipuram in Tamil Nadu
(6) and Talwandi Sabo in Punjab (6). Each has square panchayat boundaries, villages, a Region with one GeoCell per
panchayat, a Hub, a Grid, a pelletizer and a Mitra. Load one with `--site haryana`,
`--site tamilnadu` or `--site punjab`. Log in at `/mitra/` as `mitra1` (Haryana), `mitra2`
(Tamil Nadu) or `mitra3` (Punjab), password
`mitra-demo-123` (change it for anything real). The state, district and block names are right but
the panchayat names and shapes are samples, not official data. Safe to re-run.

## Biomass supply estimate

Estimated collectable biomass = plot area (acres) x tonnes per acre for the crop, less the
state's pilferage (expected loss) percentage. Nothing is stored, so it updates as soon as plots,
crops or figures change. Set the figures under **Reference > Biomass types**: each type has a
default tonnes-per-acre (Paddy straw 1.3, Mustard stalk 1.2 to start; the others are empty until
you fill them in) and, on the same page, an optional row per state with that state's own
tonnes-per-acre and pilferage percent. Crops with no figure are left out and listed as a warning.

Admins see it at `/admin/reports/supply/` (by crop, Grid and GeoCell, for a chosen year, season
and Region). A Mitra sees the total for their own Grid on the dashboard.

## Posting a requirement

Demand > Requirements (Admin). Pick the factory and the product, the volume needed in tonnes,
the earliest and latest delivery dates, and optionally a rough target GCV and quality notes. The
GCV is a figure a person types in; nothing checks it against a product's grade or matches it to
supply. As deliveries are agreed, update the volume met and the status (open, partly met,
fulfilled, cancelled). The list also shows how much of that product has been reported as made across
the network, as a rough guide. Buyers do not log in in V1, so an Admin posts on their behalf.

## Collection, stock and output

A Mitra logs each **pickup** from a farmer (residue type, tonnes, total rupees paid, date) from
the farmer's page, and reports **output** (pellets, briquettes and so on, with a rough quantity
and, if known, the residue used up) from the Stock page. Both are stored against the Mitra's Grid,
and a Hub sees them through its Grids. The Stock page shows the running tally: collected, paid,
average rupees per tonne, made, and **on hand** (collected minus residue reported as used), plus
this year's collection against the supply estimate. Admins see every Hub and Grid at
`/admin/reports/stock/`. Quantities are in tonnes and prices in rupees. Mitras cannot edit a
record after saving; an Admin can correct or deactivate one in the admin.

## The Mitra web page

Log in at `/mitra/` with a Mitra's own account (Accounts > Users, role Biomass Mitra, linked
to the Mitra record). A Mitra can register a farmer (consent tickbox required, duplicate mobile
numbers are flagged), add plots (latitude and longitude, or "Use my location" on a phone, and the
area in acres) and record crops per season. A Mitra sees only farmers they registered or who farm
in their Grid's cells. It needs an internet connection; the offline version comes later.

## Offline Mitra app

Open `/mitra/app/` on the phone (once, with a signal) and add it to the home screen. After that it
opens with no signal. It downloads the Mitra's farmers and the lists (villages, crops, residue
types, products), and everything the Mitra enters is saved on the phone first: new farmers (with
consent), plots, crops, pickups and output reports. When a signal is back it sends the changes
in order. Each change carries an id made on the phone, which the server uses as the record's id, so
a change sent twice is only saved once. A farmer whose mobile number matches another farmer is
saved but flagged **Needs review** (Admin > Farmers, with an action to clear it); nothing is ever
merged automatically. A change the server rejects stays on the "To send" screen with the reason,
and can be retried or discarded. If the login has expired, the phone keeps the changes and asks for
a new login. Not yet in the offline app: editing or deleting a saved record, drawing a plot boundary,
and offline login.

To check the app in a real browser with the network switched off (needs Node, Playwright and Chromium):
`NODE_PATH=$(npm root -g) node apps/field/js_tests/offline_smoke.mjs`

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

## Dispatch, sales and the ledger

**Fee schedules (Admin > Trade > Fee schedules).** Each Region has one schedule in force at a time, using one of three models:
flat rupees per tonne, a percentage of the sale value, or a lease (fixed rupees per month per Grid, nothing on each sale).
To change the model, set an end date on the current schedule and add the next one.

**Dispatch.** A Mitra opens *Dispatch* in the Mitra app to send processed product (only what has been made and not yet sent) to a
buyer's factory. Admin staff then record each step on the dispatch page: received at the Hub, left for the buyer, delivered
(or cancelled). Each step records a weight, and weight can only go down along the way. The difference is shown as loss.

**Sale.** Once a lot is delivered, Admin records the sale (Trade > Sales). The buyer pays Regenerix. The sale is split as:

    sale value = farmer payment + Regenerix platform fee + Mitra margin

The platform fee comes from the Region's fee schedule. The farmer payment is typed in, or left empty to use the Grid's average
pickup price x the delivered weight (marked as an estimate). The Mitra margin is whatever remains. Use the actions on the
Sales list to mark the buyer's payment received and then the Mitra settled. Lease charges are added under Trade > Lease charges.
Sales cannot be edited afterwards.

**Ledger.** Every dispatch step, sale, payment, settlement and lease charge is written to an append-only ledger. Each entry
includes a fingerprint of the one before it, and the database refuses any edit or delete. This is a tamper-evident log inside our
own database, not a public blockchain. Check it with `python manage.py verify_ledger` or on Admin > Ledger.

## Customer stock (first slice of the customer platform)

Customers (buyers) get their own login at `/customer/` and see only their own company's stock.

**Try it:** `docker compose exec web python manage.py load_demo_customer`, then log in at `/customer/` as `customer1` / `customer-demo-123`.
This adds "Sample Power Ltd" with four yards, eleven piles and made-up counts. Safe to re-run.

**Setting up a real customer (Admin > Customers):** link a login with the Buyer role to the company (Customer members), set the plant's
daily burn (Plant profiles) and its maximum moisture on the Factory, add Stockyards with their Piles, then add Batches.
Adding a batch records its receipt and any intake moisture reading.

**The numbers on the overview**
- *Book inventory*: the sum of a batch's stock transactions (receipts, burning, losses, moves, adjustments). Never overwritten.
- *Physical inventory*: the latest physical count plus movements recorded after it.
- *Usable inventory*: physical stock whose latest **measured** moisture reading is within the plant's limit. A batch with no count or no reading is not usable.
- *Available to use*: usable minus reservations. *Fuel cover* = available ÷ the plant's daily burn.
- Each batch shows how well its quantity is known: Verified, Calculated, Estimated (survey counts) or Overdue (count older than `STOCK_VERIFICATION_DAYS`, 14 by default).

Stock records are added, not edited: a correction is a new transaction or count. Every one is written to the tamper-evident ledger.

**Not built yet** (see the product spec): contracts and delivery schedules, weather alerts, fire-risk monitoring, the yard app, customer-facing dispatch and finance, ESG reports.
