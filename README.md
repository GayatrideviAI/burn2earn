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

## Contracts, purchase orders and deliveries

**Setting up (Admin > Customers):** add a *Contract* for a customer with its period, penalty terms, and who bears spoilage risk, with one
*line* per product (contracted tonnes, price, moisture and GCV limits). On a Contract line, the action "Spread the contracted tonnes
evenly" creates the monthly plan. Add *Purchase orders* against a line: plant, tonnes and a delivery window.

**Delivering against an order:** when a Mitra creates a dispatch (or Admin does, under Trade > Dispatches) they can pick the open purchase order it
is for. The plant and product must match. Delivered means the dispatch reached the buyer (stage Delivered), counted at the weight taken at
the gate. Loads still moving are shown as "on the way". Cancelled loads count for nothing.

**What the customer sees** (`/customer/contracts/`): contracted, ordered, on the way and delivered per product; planned vs delivered for each month;
late orders and contracts that are behind (more than 15 points behind the share of the period gone); and every load with its vehicle and date.

**Who supplied it:** lots are not tagged farmer by farmer, so each delivered dispatch is shared out between the farmers who handed over that biomass
at the supplying Grid, in proportion to tonnes handed over up to the delivery date. Customers see Mitra name and code, Grid, and farmer **code and village only**
(never name or mobile). Treat it as a fair attribution, not lot-level proof.

Try it: `docker compose exec web python manage.py load_demo_deliveries` (loads the demo network and customer too if missing), then log in at `/customer/`.

## From delivery to yard: the chain from farmer to customer

A delivered load can be put into the customer's yards as one or more **batches** that remember which load they came from. In Admin, add a Batch and pick
the delivered load (*Source dispatch*). The weight available is what was weighed at the buyer's gate, and a load cannot be received for more than that.
The Grid and a source note are filled in for you, and the load's code is written into the ledger entry for the receipt.

**What the customer sees:** on each batch, a *Chain of custody*: farmers (code and village), the Mitra and Grid, the dispatch with its loading and gate
weights, the purchase order and contract, the yard and pile, and what has happened since (burned, lost by cause, still on the books). On each purchase order,
every load shows which batches it went into, or "n t not in a yard" when part of a delivered load is unaccounted for (this also appears in "what to do next").

**For staff:** `/admin/reports/trace/` follows one farmer's residue by farmer code, load by load, to the customer, the yard batch and how much of that batch was burned.
As before, farmers are credited in proportion to what each handed over at the supplying Grid, so this is an attribution, not lot-level proof.

Try it: `docker compose exec web python manage.py load_demo_deliveries` (the first two demo loads go into yards, the third is left unreceived).

## Yard measurement and fire/spoilage risk

A new **Yard operator** login (`/yard/`) is for the person who walks the stockyard. In Admin, add a Yard operator, link them to a user with the role
"Yard operator" and tick the yards they look after. They can log a **temperature probe reading** (with the spot and depth), a **walk-round inspection**
(wet, mould, steam or smell, cover in place), a **stock count**, a **moisture reading**, and the **size and cover** of a pile. Everything goes through the
same services as the rest of the system and is written to the ledger.

Each pile gets a risk level from plain rules, not a trained model: Normal, Needs attention, Watch closely, Check twice a day, Fire likely. The rules look at the
hottest spot, how fast the temperature is rising (with an estimate of days until the 65 °C step), how old the last reading is (a pile nobody has probed is never
shown as safe), the last inspection, damp stock at intake and stack height. Every flag lists its reasons. Piles at Watch or above raise an **alert**, which
escalates, closes itself when the pile cools, and records who acknowledged it and how quickly. Customers see the risk on their overview, yard and batch pages,
plus a **Use first** list that ranks piles by risk and then age.

**The thresholds are assumptions.** They live in `config/settings.py` (`YARD_*`) and must be validated with a fire-safety partner for baled paddy straw before
anyone relies on them. A probe only shows the temperature at its own spot, so this is an early-warning aid, not a guarantee. A trained model should wait for real yard data.

Try it: `docker compose exec web python manage.py load_demo_yard` then log in at `/yard/` as `yard1` / `yard-demo-123`.

### Offline yard app

Open `/yard/app/` on the phone once, with a signal, and add it to the home screen. It then opens with no signal. It downloads the operator's piles
(latest temperatures, batches, open alerts and the last risk level), and everything entered is saved on the phone first: temperatures, inspections,
stock counts, moisture readings, pile size and cover, and "I have seen this" on an alert. The time of each reading, inspection and acknowledgement is the time
on the phone when it was entered, so a reading taken in a dead zone keeps its real time. Changes go up in order when a signal returns; each carries an id made
on the phone, so a change sent twice is saved once, and a change the server rejects stays on the "To send" screen with the reason.

The risk level is worked out on the server. With no signal the phone shows the last level it downloaded and raises it at once, with the advice, if the temperature or
inspection just entered is worse. It never lowers a level by itself. It is shown as "raised on this phone" until the server confirms it. Not in the offline app:
editing or deleting a saved record, and offline login.

Check it in a real browser with the network switched off (needs Node, Playwright and Chromium):
`NODE_PATH=$(npm root -g) node apps/yardops/js_tests/offline_smoke.mjs`

**Not built yet:** weather and rain risk, WhatsApp/SMS alerts.

## Weight photos (collecting data to predict weight from a photo)

**No weight is predicted yet.** This step collects photos together with the true weight so a model can be trained and checked later, once there is enough real data.
In the offline **Yard app** and **Mitra app** the person can photograph **a stack** (in the yard app, a pile in their yard) or **a loaded vehicle** (tractor trolley, truck,
mini truck). They can add the number of bales if counted, something in the photo that shows size (a 2 m pole, say), and the **weighbridge slip weight and slip number**,
either at once or later from the **Photos** screen, which lists sent photos still missing a weight. Photos are shrunk on the phone, queued on the phone and uploaded one by one
when there is a signal, before the other changes. Each photo has an id made on the phone, so a retry saves it once.

The server checks that the file is really a photo, saves it as a JPEG with no location or camera details, records a fingerprint (SHA-256) of the original in the tamper-evident ledger, and keeps it
under `media/weight_photos/`. A photo is never replaced or deleted. A weight can be added once from the phone; **staff correct a wrong one in Admin > Weight photos**, and the correction goes
to the ledger. Photos are shown only to staff and the person who took them (`/weight-photos/<id>/image/`).

* **Coverage:** `python manage.py weight_photo_report` shows photos and weighed photos per kind against a target of 300 each. The target is a guess (`WEIGHT_PHOTO_TARGET_PER_SUBJECT`); a data scientist should set it.
* **Training set:** `python manage.py export_weight_dataset <new folder>` writes `labels.csv` and `images/` for photos that have a weight. Admin can also download a CSV of selected photos.
* **Docker:** Pillow was added to `requirements.txt`, so rebuild the image (`docker compose up -d --build`). Photos live in the `media/` folder (ignored by git); back it up and move it to proper file storage before production.
* **Privacy:** the apps tell people to keep faces out of photos, but photos may still show people. How long to keep them and how consent works should be reviewed by counsel before this is used with real data.

## Hindi and Punjabi (customer pages and Mitra app)

The customer pages (`/customer/`), the Mitra pages (`/mitra/`) and the offline Mitra phone app can be shown in English, हिन्दी and ਪੰਜਾਬੀ. A switch in the top bar changes the language and the choice is remembered on the device. This covers every page, form label, confirmation and error message, alert text, stage and type label, and the unit (t for tonnes). The offline phone app carries its own translation table, so switching language works with no signal. The admin is not translated. Farmer-facing data that comes from the database (crop, village, product and biomass names) is shown as entered.

**The first draft has not been checked by anyone who speaks the local dialects.** About 45 phrases still show the English word in both languages (yellow in the sheet), where I was not sure of the wording.

How the field check works:

1. Open `locale/translations.xlsx`. Column A is the English, B is Hindi, C is Punjabi, and the App column says whether a phrase is in the customer app, the Mitra app, the yard app or several. Yellow cells still show English. Fix or fill in B and C, use the Status and Comments columns, and leave column A alone.
2. Keep every `%(name)s` exactly as written; the page puts a number or name there.
3. Put the returned sheet at `locale/translations.xlsx` and run:

```
docker compose exec web python manage.py translations import
```

That loads the sheet into `locale/hi` and `locale/pa` (a cell with a broken `%(name)s` is skipped and reported), and rebuilds the files Django reads. Restart the web container to pick them up.

Other commands, all `python manage.py translations <action>`:

| Action | What it does |
|---|---|
| `extract` | Finds every marked phrase in the templates and code and adds new ones, blank, to the `.po` files |
| `export` | Writes a fresh `locale/translations.xlsx` from the `.po` files |
| `import` | Reads the sheet back and compiles |
| `compile` | Rebuilds the `.mo` files from the `.po` files |

No gettext programs are needed: the tooling is plain Python (`apps/customers/i18n_tools.py`). A test fails if a new phrase is marked but not extracted, or if the `.mo` files are out of date.

When adding a customer-facing word: in a template use `{% trans "Text" %}` or `{% blocktrans trimmed with x=value %}... {{ x }} ...{% endblocktrans %}` (no plurals, no filters inside); in Python use `gettext` (`_`) at request time and `gettext_lazy` for model choices and form labels; in the phone app (`apps/field/static/field/app.js`) use `t("Text %(name)s", {name: value})`. Weights go through the `|tn` filter so the unit is translated. Then run `extract`, `export`.
