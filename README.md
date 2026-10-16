# Philadelphia Community Outreach Planner

A map app for the community development office to compare possible outreach
areas in Philadelphia. Draw or pick a polygon and it reports modeled
demographics (population, age, race, income, housing, commuting, education)
built from ACS census data and placed onto real buildings.

Live site: <https://tufirm.github.io/philadelphia-community-outreach-planner/> (public,
GitHub Pages). Outreach members and the proposed area of focus are never on the
site: users load them from their own computer (see
[Private files](#private-files-outreach-members-and-the-area-of-focus)).

---

## How the numbers are made

```
ACS tracts (census)  ─┐
OPA properties       ─┼─►  building model  ─►  building_weights_web_*.csv ─►  web app
Building footprints  ─┤    (script 02)          (script 03)                 (docs/)
Vacancy indicators   ─┘
```

1. **Census is the master data.** Every tract's households, owners, renters
   and people come from the ACS 5-year estimates.
2. **Footprints say where people live.** OPA records are matched to building
   footprints; OPA says how many units each building has, which look
   owner-occupied (homestead exemption) and which are vacant.
3. **Each tract is balanced back to the census.** Occupied owner and renter
   units are scaled so they add up to the tract's ACS numbers, vacant buildings
   get zero, and people = owner units × owner household size + renter units ×
   renter household size.
4. **Group quarters go to group-quarters buildings.** Dorms (including
   university-owned residential buildings), nursing homes and prisons get the
   tract's group-quarters population and no household units. A tract with no
   such building puts them in institutional buildings, then in non-commercial
   ones, so nobody is dropped.
5. **Big apartment buildings are scaled to the census.** Buildings whose units
   are estimated from floor area (usually towers on one OPA account) are scaled
   per tract so housing units add up to the ACS count.
6. **In the app**, a polygon's share of each tract is taken from the buildings
   inside it: people counts by population, household counts by occupied units,
   owner and renter counts by owner and renter units.

This is a model, not address-level census data. `docs/data/tract_model_qa.csv`
lists every problem a tract has in its `flag` column (separated by `; `):

| Flag | Meaning |
|---|---|
| `FEW_OPA_UNITS` / `MANY_OPA_UNITS` | OPA units under 70% / over 140% of ACS housing units |
| `GQ_NOT_PLACED` | more than 50 group-quarters residents not placed |
| `GQ_FALLBACK` | group quarters placed in non-commercial or any buildings (no GQ or institutional building) |
| `USED_FALLBACK` | households placed by floor area because the tract has no usable housing |
| `NEW_CONSTRUCTION` | buildings from 2020 on hold over 10% of ACS housing units (may postdate the ACS sample) |

---

## Folder layout

```
philadelphia-community-outreach-planner/
├── README.md
├── DATA_SOURCES.md           every dataset: source link, raw/processed files, internal/external
├── requirements.txt          Python packages
├── .env.example              copy to .env and fill in (never commit .env)
├── .gitignore
├── templates/                outreach intake template
├── scripts/                  run in order, from the repo root
│   ├── common.py             shared folder paths
│   ├── 01_download_acs_tracts.py      (was philly_acs_tracts.py)
│   ├── 02_build_building_model.py     (was philly_building.py)
│   ├── 03_prepare_web_data.py         (was prepare_web_data.py)
│   ├── 04_download_reference_layers.py  police districts, ZIPs, wards, divisions
│   ├── 05_outreach_heatmap.py           private outreach file (loaded in the app)
│   ├── 06_crime_data.py                 PPD crime, shootings, stops; PSAs and divisions
│   ├── 07_publish_reference_layers.py   copies hand-placed layers from data/raw/reference/
│   ├── 08_address_lookup.py             public OPA address lookup for in-browser matching
│   └── 09_community_orgs.py             community organizations (list + OSM) and RCOs
├── data/                     NOT in git (big or private); on the S: drive it sits next to
│                             this folder and .env points PLANNER_DATA_DIR at it
│   ├── raw/                  downloads you put here yourself
│   │   ├── reference/        editable copies of hand-placed layers (city/, temple/, project/)
│   │   └── outreach/         member exports (private!)
│   ├── private_app_files/    outreach CSV + area of focus, loaded in the app (never published)
│   └── processed/            everything the scripts create
│       ├── acs/
│       ├── building_model/
│       ├── crime/
│       └── outreach/
└── docs/                     the website (GitHub Pages serves this folder)
    ├── index.html
    └── data/                 small files the site loads
```

---

## First-time setup

```bash
git clone https://github.com/TUFIRM/philadelphia-community-outreach-planner.git
cd philadelphia-community-outreach-planner
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Windows   (macOS/Linux: cp .env.example .env)
```

Edit `.env`:

- `CENSUS_API_KEY`: free at <https://api.census.gov/data/key_signup.html>
- `PLANNER_DATA_DIR`: optional. Point it at the S: drive folder if you keep the
  big files there. That folder needs `raw/` and `processed/` inside it.

## Get the raw data (into `data/raw/`)

All from [OpenDataPhilly](https://opendataphilly.org):

| File name to save as | Dataset |
|---|---|
| `OPA_PROPERTIES_PUBLIC.csv` | Property Assessments (full CSV, ~580,000 rows) |
| `LI_BUILDING_FOOTPRINTS.geojson` | Building Footprints |
| `Vacant_Indicators_Bldg.geojson` | Vacant Property Indicators – Buildings |

Optional:

- `group_quarters_buildings.csv` with one column, `BUILDING_ID` (the footprint
  BIN), listing dorms and nursing homes the OPA descriptions miss. Temple
  residence halls are the big one. Without this, student population near
  campus gets spread over row houses.
- `outreach/gateway_clients.csv`: the member export, in the standard intake layout
  (`ID, Status, Street, Unit, City, State, ZIP`) or the older `ID, Status, Address`.

## Run the pipeline

```bash
python scripts/01_download_acs_tracts.py        # ~1 min
python scripts/02_build_building_model.py       # 10-30 min
python scripts/03_prepare_web_data.py
python scripts/04_download_reference_layers.py
python scripts/05_outreach_heatmap.py           # private outreach file; only when the member list changes
python scripts/06_crime_data.py                 # 20-40 min the first time; monthly after that
python scripts/07_publish_reference_layers.py   # only after editing data/raw/reference/
python scripts/08_address_lookup.py             # after refreshing OPA (address lookup for the app)
python scripts/09_community_orgs.py             # after editing the CBO list; also refreshes RCOs
```

Where every dataset comes from, and where to edit it, is in `DATA_SOURCES.md`.

### Pulling newer City and Census data

`scripts/update_data.py` refreshes the public data, rebuilds what depends on it,
runs `check_data.py`, and with `--push` commits and pushes `docs/data` only if
every check passes. It never touches the private files.

```bash
python scripts/update_data.py                 # monthly: crime + boundary layers, then check
python scripts/update_data.py --push          # ...and commit + push if the checks pass
python scripts/update_data.py --all --push    # also re-download OPA, footprints and vacancy,
                                              # and rebuild ACS tracts, model and address lookup
```

`--raw` downloads OPA from the City's bulk file and the footprints and vacancy
layers from the City's ArcGIS services; `--acs` is for a new ACS 5-year release
(usually each December).

Script 06 downloads every PPD crime incident (2006 on), shooting victim (2015
on) and vehicle/pedestrian stop (2014 on), snaps each to the nearest street
segment within 300 ft (a record equally close to several segments, at an
intersection, is split evenly among them), keeps complete months per dataset
(stops are published a few weeks after incidents), and writes `docs/data/crime/` plus `police_psa.geojson` and
`police_divisions.geojson`. Raw downloads are cached in
`data/processed/crime/raw/`, so later runs only re-fetch the last two years.
`--start 2015` builds fewer years; `--refresh` re-downloads everything.
`docs/data/crime/meta.json` records QA per year and dataset: records,
`no_coordinates`, `not_on_a_street`, `no_district`, `no_psa`,
`intersection_ties` and `snap_ft_p95`, plus `dup_seg_ids` for the centerlines.
Since 2023 PPD places records off the centerline (2025: median 54 ft), so
check `snap_ft_p95` and `not_on_a_street` after each run.
Police contacts for popups live in `docs/data/police_contacts.json`. Edit it
by hand when a captain changes (check phillypolice.com).

Script 02 prints an **OPA / footprint diagnostics** block. Check it the first
time. The earlier model placed only ~85,000 units for ~680,000 households, and
these numbers show where records get lost:

- *OPA records read* should be about 580,000. Far fewer means a partial export.
- *Footprints with residential* should be in the hundreds of thousands.
- *Median people per occupied unit* at the end should be about 2.2.

Preview the site locally:

```bash
python -m http.server 8000 --directory docs
# open http://localhost:8000
```

---

## Hosting (GitHub Pages)

The site is public on **GitHub Pages**, served from the `docs/` folder of
`main`. Everything in `docs/` (and the whole repo) can be seen by anyone, so
nothing private goes there:

- outreach members and the proposed area of focus are loaded by each user from
  their own computer (Load private files), never committed;
- the Census API key lives only in `.env`, which git ignores.

Settings: repo **Settings → Pages → Build and deployment → Deploy from a branch
→ `main` / `/docs`**. Each push to `main` updates the site in a minute or two.

### Before every push

```bash
python scripts/check_data.py     # fails if private files are in docs/ or a file is too big
git status                       # nothing under data/, .env or private files listed
```

### Updating the site

```bash
git pull
# ...edit, or re-run scripts...
python scripts/check_data.py
git add -A
git commit -m "Describe the change"
git push                         # GitHub Pages republishes docs/
```

Preview locally before pushing:

```bash
python -m http.server 8000 --directory docs
# open http://localhost:8000
```

### File sizes

GitHub warns about files over 50 MB and rejects files over 100 MB. Script 03
splits the building weights into `building_weights_web_1.csv`, `_2.csv`, ...
(about 15 MB each, listed in `building_weights_parts.json`), which also lets the
browser download them in parallel. `scripts/check_data.py` flags any `docs/`
file over 25 MiB.

---

## Private files: outreach members and the area of focus

Two things are **never published** on the site or in the repo: the outreach
member data and the proposed boundary ("Original Proposed Area of Focus").
The other 9 planning areas are public (`docs/data/Polygons_of_interest.geojson`).
The private files live in
`data/private_app_files/` (next to this folder on the S: drive, never in git)
and are loaded into the app from your computer:

**Layers tab (or Plan tab) → Load private files… → select one or both files.**
The browser reads them locally; nothing is uploaded.

| File | Made by | In the app |
|---|---|---|
| the member export itself (`ID, Status, Address` or the standard intake columns) | the program's spreadsheet | matched to City addresses **in the browser** (nothing is sent anywhere), then the same as below |
| `outreach_private.csv` | `scripts/05_outreach_heatmap.py` | outreach heat map, member counts in every polygon, ZIP popups |
| `Original_Proposed_Area_of_Focus.geojson` | the proposed boundary, cut out of the My Maps KML plan | added to the 9 public planning areas |

- Loading the export directly places members whose address is in the City's
  OPA list (about 600 of 980 today); `outreach_private.csv` from script 05
  also uses the Census geocoder and places more (about 810).
- The outreach layer is not saved by the app; load it again each visit.
- Plan areas autosave in the browser like any plan. On a shared computer, clear
  the plan when done.
- "Save changes" still saves only new or edited polygons. To reopen that file
  later, load `Original_Proposed_Area_of_Focus.geojson` first, then use **Open plan**.
- `scripts/check_data.py` fails if an outreach file or the area of focus appears in `docs/`.

The member export itself (home addresses) stays in `data/raw/outreach/`.
Script 05 turns it into `outreach_private.csv`:

- map rows (`kind=map`): one per street block, with counts by status
- ZIP rows (`kind=zip`): counts per ZIP code. Members with a map location but no
  ZIP in their address get the ZIP polygon they fall in.

### Standard address intake

New member records should use these columns
(`templates/outreach_intake_template.csv`):

| Column | What goes in it | Example |
|---|---|---|
| `ID` | Member ID | `1` |
| `Status` | `Active`, `Disengaged`, `Milestone complete` or `Inquiry` | `Active` |
| `Street` | House number and street only. No apartment, city or ZIP | `1915 W Spencer Ave` |
| `Unit` | Apartment or unit, blank if none | `Apt 2` |
| `City` | City | `Philadelphia` |
| `State` | Two-letter state | `PA` |
| `ZIP` | 5 digits only | `19141` |

Script 05 reads this layout or the older one-field export (`ID, Status,
Address`). A member can only be placed on the map with a house number and
street; a ZIP alone counts in the ZIP table only.

### Updating the outreach file

1. Save the new member export over `data/raw/outreach/gateway_clients.csv`,
   or point the script at the downloaded file with `--input`.
2. Run `python scripts/05_outreach_heatmap.py` (add `--grid` for ~250 m cells
   instead of street blocks), for example:
   `python scripts/05_outreach_heatmap.py --input "C:/Users/you/Downloads/Gateway Clients - Heat Map 1.csv"`.
   The export can be the standard intake layout or the one-column `Address`
   export straight from Google Sheets/Excel (multi-line addresses, a BOM and
   text before the house number are handled; P.O. boxes and phone numbers are
   skipped).
3. In the app, **Load private files** → `outreach_private.csv`.

Each member sits at the middle of their street block (never their house), and
the app counts those points inside polygons. Members outside the city keep
their ~250 m cell center, because the City's street centerlines stop at the
city line. Every block is shown, including blocks with 1 or 2 members: the file
is private and only ever loaded on the user's own computer (decided
2026-10-16). Raise `MIN_MEMBERS_PER_CELL` in script 05 if it is ever shared.

---

## App features

- Draw, edit, cut, drag and delete planning polygons; **Undo / Redo** (buttons,
  map control, Ctrl+Z / Ctrl+Y). While drawing, Ctrl+Z removes the last corner.
- The map pans when the cursor reaches its edge while drawing, or while
  dragging a corner.
- Reference outlines: council districts, police districts, political wards,
  voting divisions, ZIP codes, and Temple's 8 priority ZIPs (19121, 19122,
  19123, 19125, 19130, 19132, 19133, 19140). Click any of them for demographics.
- **Style** any layer or polygon: color wheel, hex, brightness, and
  transparency sliders. Polygon styles save into the plan GeoJSON; layer
  styles are remembered in the browser and saved with the plan.
- Polygon labels use each polygon's own color.
- **Save changes** writes only new or edited polygons (plus a list of removed
  base polygons). **Open plan** puts those changes back on top of the base
  polygons.
- **Copy** duplicates a polygon so you can edit a variation.
- Police stations: hover for the district, click for address and phone.
- Outreach member heat map with a status filter (All, Active, Disengaged, and
  so on).
- **Hide the side panel** to explore the map: the « Hide button, the ☰ / «
  button at the top of the map, or the `[` key. The choice is remembered.
- **Compare** any two areas: each side picks a source (planning polygons, the
  whole plan, a loaded saved plan, or a boundary layer such as ZIP codes,
  wards, voting divisions or NACs) and then the specific one. Plans are listed
  first. A and B are outlined on the map while the tab is open.
- **Neighborhood Advisory Committees**: NAC service areas (click for
  demographics plus the NAC's coordinator and contact) and NAC office points.
  Files: `docs/data/NeighborhoodAdvisoryCommittees.geojson` and
  `docs/data/NAC_Offices.geojson`.
- **Community Organizations** (off by default): the FIRM CBO list
  (`data/raw/north_philly_cbos_contacts.csv`) plus community centers, food
  pantries and service organizations found in OpenStreetMap, limited to the
  8 priority ZIP codes. Colored by type (a two-color dot = two types; a dark
  outline = on the FIRM list); click one for its contact details. Homes,
  shelters, nursing homes, recovery residences, unions and fraternities are
  left out. Script 09 also writes `data/processed/community_orgs/cbos_review.csv`
  for checking what was added. File: `docs/data/cbos.geojson`.
- **Registered Community Organizations** (off by default): City RCO boundaries
  that touch a priority ZIP, each in its own color. Click one for its name,
  meeting place, primary and alternate contacts and demographics. Contacts'
  home addresses are not published. File: `docs/data/rcos.geojson`.
- **Pick features in any layer**: click a layer's feature count (for example
  "152 features") to list its features, search them, and tick all, none or
  some to choose which are shown on the map ("135 of 152 features shown").
- **Places of interest** (Layers tab, off by default): businesses, places of
  worship, schools, health care, civic places and parks from OpenStreetMap,
  shown at street zoom. Clicking one opens a place card with Directions,
  Google Maps and Street View links. Right-click anywhere on the map for the
  same Google links for that spot. No API key is needed.
- **Street View dropper** (yellow figure under the zoom buttons): drag it onto
  the map, or click it and then click a spot (Esc cancels), to open Google
  Street View there in a new tab. No API key is needed.
- **Crime** tab: PPD crime incidents, shooting victims and vehicle (traffic)
  and pedestrian stops. Pick an offense (totals, violent = UCR 100, 200, 300,
  400, 800, nonviolent, any single code or offense) and two periods (a month,
  a year or a range). Everything is an average per month; change is B − A,
  never a percentage. The map shows street segments up close, PSAs and
  districts farther out (or one geography you pick). Charts mark COVID-19 and
  periods A and B; DAO-style tables break the numbers down by offense and by
  district. The Demographics and Compare tabs gain crime rows, and the tab
  lists the data limits.
- **Police divisions, districts and PSAs**: click any of them (or a police
  station) for the commanding officer, address, phone and email.
- **Street centerlines** (Plan tab, off by default), from the City's live
  `Street_Centerline` service:
  - the checkbox shows every centerline in the city (loaded once per
    session), and while drawing or editing, corners snap to them (hold Alt
    to place a corner freely);
  - the **Snap** button on a planning polygon rebuilds it from whole street
    blocks: every block with at least half its area inside is kept, so edges
    run down the middle of streets and never split a row of houses. Undo
    returns to the hand-drawn outline.
