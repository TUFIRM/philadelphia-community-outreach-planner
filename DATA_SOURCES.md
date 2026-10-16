# Data Sources

Every dataset the Philadelphia Community Outreach Planner and its ArcGIS Pro project use: where it
comes from, where the editable raw copy lives, what the scripts turn it into, and
whether it is internal (Temple) or external.

*Compiled 2026-10-15 from the scripts, `docs/index.html` and the ArcGIS Pro project.
Rows marked **Unsure** need someone to confirm the origin, or re-download from the
link given.*

**Where the paths start**

- `data/...` paths start in the project folder
  `S:\Space Management\Projects\GIS - Community Engagement Tracker\`. The data lives
  outside the git clone, and the clone's `.env` points the scripts there with
  `PLANNER_DATA_DIR`.
- `docs/...` and `scripts/...` paths start in the repo folder
  `S:\Space Management\Projects\GIS - Community Engagement Tracker\philadelphia-community-outreach-planner\`.

**Internal vs external**

- **External**: published by someone outside Temple (City of Philadelphia, U.S. Census
  Bureau, OpenStreetMap, Esri).
- **Internal**: made or held by Temple: Temple's ArcGIS Online organization, the project
  team, or the program office.

**Where things live**

| Folder | What's there | In git? |
|---|---|---|
| `data/raw/` | Source files as downloaded. **Edit raw data here.** | No |
| `data/raw/reference/` | Editable copies of the map layers that have no download script. Publish edits with `scripts/07_publish_reference_layers.py` | No |
| `data/processed/` | Everything the scripts create (`acs/`, `building_model/`, `outreach/`, `crime/`) | No |
| `docs/data/` | The small files the web app loads. Script output, so don't hand-edit (except `police_contacts.json`) | Yes |

---

## 1. Demographic model inputs

These feed the population model (scripts 01–03).

| Dataset (name at source) | Used for | Raw file (edit here) | Processed file(s) | Source link | Internal / External |
|---|---|---|---|---|---|
| **American Community Survey 5-Year Estimates, 2020–2024**: tables B01001, B01003, B03002, B08201, B08301, B14001, B15003, B17001, B19013, B23025, B25001, B25003, B25008, B25010, B25064, B25077, B27001, B28002, C16001, C18108 | Master tract totals: population, households, owners/renters, income, poverty, race, age, commuting, education, employment, rent and home value | No file. Script 01 pulls the numbers from the Census API each run. To add or change variables, edit the `VARIABLES` list in `scripts/01_download_acs_tracts.py` | `data/processed/acs/philly_tracts_acs2024.gpkg`, `.csv`, `field_dictionary.csv`, published as `docs/data/philly_tracts_acs2024.csv` | API: <https://api.census.gov/data/2024/acs/acs5> · About: <https://www.census.gov/data/developers/data-sets/acs-5year.html> | External (U.S. Census Bureau) |
| **Cartographic Boundary File: Census Tracts, Pennsylvania, 2024** (`cb_2024_42_tract_500k`). Fallback: TIGER/Line `tl_2024_42_tract` | Tract shapes for the ACS data | `data/processed/acs/cb_2024_42_tract_500k.zip`, downloaded and cached by script 01. Delete it to force a fresh download | Joined into `philly_tracts_acs2024.gpkg` | <https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_42_tract_500k.zip> · <https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html> | External (U.S. Census Bureau) |
| **Philadelphia Properties and Assessment History** (OPA, full CSV of ~580,000 properties) | Units per building, homestead (owner) signal, land use, vacancy flag. Script 05 also uses it to match outreach addresses | `data/raw/OPA_PROPERTIES_PUBLIC.csv` | `data/processed/building_model/` (see below) | <https://opendataphilly.org/datasets/philadelphia-properties-and-assessment-history/> | External (City of Philadelphia, Office of Property Assessment) |
| **Building Footprints** (L&I, service `LI_BUILDING_FOOTPRINTS`) | Where people can live; one row per building (BIN) | `data/raw/LI_BUILDING_FOOTPRINTS.geojson` | `data/processed/building_model/` | <https://opendataphilly.org/datasets/building-footprints/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=ab9e89e1273f445bb265846c90b38a96) | External (City of Philadelphia, Dept. of Licenses & Inspections) |
| **Vacant Property Indicators – Buildings** (service `Vacant_Indicators_Bldg`) | Vacant buildings get zero households in the model. The app also queries it live to draw vacant footprints | `data/raw/Vacant_Indicators_Bldg.geojson` | `data/processed/building_model/philly_buildings_vacant.gpkg` | <https://opendataphilly.org/datasets/vacant-property-indicators/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=f7ed68293c5e40d58f1de9c8435c3e84) | External (City of Philadelphia) |
| **Group-quarters building list** (optional, column `BUILDING_ID`) | Places dorm and nursing-home population the OPA descriptions miss (Temple residence halls) | `data/raw/group_quarters_buildings.csv`: **doesn't exist yet**. Create it by hand if needed | Used inside script 02 | n/a (hand-made) | Internal (would be made by the project team) |

**Address lookup** (script 08, from the OPA file): `docs/data/addresses/*.json`, one file per first letter of the
street name, with every OPA address point. Public City data; the app uses it to place a member export in the browser.

**Building model outputs** (script 02 writes these to `data/processed/building_model/`):
`philly_buildings_master.gpkg`, `philly_buildings_residential.gpkg`,
`philly_buildings_vacant.gpkg`, `philly_building_points.gpkg`, `building_summary.csv`,
`opa_to_building_crosswalk.csv`, `unmatched_opa_points.csv`, `tract_model_qa.csv`.
Script 03 turns them into `docs/data/building_weights_web_1.csv`, `_2.csv` (split by tract into ~15 MB files;
`building_weights_parts.json` lists the parts) and
`docs/data/tract_model_qa.csv`. The big model files stay in `data/processed/building_model/` on the S: drive;
FIRM shares them on request (the app says so).

## 2. Outreach program data

| Dataset | Used for | Raw file (edit here) | Processed file(s) | Source link | Internal / External |
|---|---|---|---|---|---|
| **Outreach member list** (standard intake `ID, Status, Street, Unit, City, State, ZIP`, or older `ID, Status, Address`; template in `templates/`). **Private: home addresses** | Outreach heat map and member counts per polygon | `data/raw/outreach/gateway_clients.csv` (git-ignored; never commit or share) | `data/processed/outreach/outreach_geocoded_private.csv` (private), and `data/private_app_files/outreach_private.csv` (street-block points plus ZIP counts). **Not published**: loaded in the app from your computer with Load private files | None (member export) | Internal. **Unsure** which system it's exported from and who owns it. Confirm with the program office (Community Impact & Civic Engagement) |
| **Census Geocoder: batch address service** | Script 05 places addresses that don't match OPA. Only the street address is sent | n/a (web service) | n/a | <https://geocoding.geo.census.gov/geocoder/> | External (U.S. Census Bureau) |

## 3. Boundary layers downloaded by script 04

Script 04 downloads these from the City's ArcGIS Online services straight into
`docs/data/`. **There is no separate raw copy**: the City service is the source.
Re-run `python scripts/04_download_reference_layers.py` to refresh them. Don't
hand-edit them, because the next run overwrites the files. If a file is missing,
the app loads the live service instead.

City ArcGIS REST base: `https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/`

| Dataset (service name) | Processed file | Source link | Internal / External |
|---|---|---|---|
| **Police Districts** (`Boundaries_District`) | `docs/data/police_districts.geojson` | <https://opendataphilly.org/datasets/police-districts/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=62ec63afb8824a15953399b1fa819df2) | External (City / Philadelphia Police Dept.) |
| **Zip Codes** (`Zipcodes_Poly`). Script adds the `temple_priority` flag for 19121, 19122, 19123, 19125, 19130, 19132, 19133 and 19140 | `docs/data/zip_codes.geojson` | <https://opendataphilly.org/datasets/zip-codes/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=b54ec5210cee41c3a884c9086f7af1be) | External (City). The priority-ZIP list is internal (Temple) and lives in scripts 04 and `docs/index.html` |
| **Political Wards** (`Political_Wards`) | `docs/data/political_wards.geojson` | <https://opendataphilly.org/datasets/political-wards/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=d67c97376d18456d98e5fa6e00415ad4) | External (City) |
| **Political Ward Divisions** (`Political_Divisions`) | `docs/data/political_divisions.geojson` | <https://opendataphilly.org/datasets/political-ward-divisions/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=160a3665943d4864806d7b1399029a04) | External (City) |

## 4. Crime and police data (script 06)

Raw downloads are cached in `data/processed/crime/raw/` (gzipped CSVs, one per
dataset and year). That folder is empty until script 06 runs. Re-runs only fetch the
last two years; `--refresh` re-downloads everything.

| Dataset (table / service) | Used for | Raw / cache | Processed file(s) | Source link | Internal / External |
|---|---|---|---|---|---|
| **Crime Incidents** (Carto table `incidents_part1_part2`, 2006 on) | Crime tab, crime rows in Demographics and Compare | `data/processed/crime/raw/` | `docs/data/crime/meta.json`, `areas.json`, `segments.json`, `seg_YYYY.json` | <https://opendataphilly.org/datasets/crime-incidents/> · API `https://phl.carto.com/api/v2/sql` | External (Philadelphia Police Dept.) |
| **Shooting Victims** (Carto table `shootings`, 2015 on) | Same | Same | Same | <https://opendataphilly.org/datasets/shooting-victims/> | External (Philadelphia Police Dept.) |
| **Vehicle & Pedestrian Investigations** (Carto table `car_ped_stops`, 2014 on) | Vehicle and pedestrian stops | Same | Same | <https://opendataphilly.org/datasets/vehicle-pedestrian-investigations/> | External (Philadelphia Police Dept.) |
| **Police Service Areas** (`Boundaries_PSA`) | PSA layer, crime by PSA | Downloaded each run, no raw copy | `docs/data/police_psa.geojson` | <https://opendataphilly.org/datasets/police-service-areas/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=8dc58605f9dd484295c7d065694cdc0f) | External (City / PPD) |
| **Street Centerlines** (`Street_Centerline`) | Snapping crime records to street segments. The app also loads it live for drawing and snapping | `data/processed/crime/street_centerline.gpkg` (cached on first run) | `docs/data/crime/segments.json` | <https://opendataphilly.org/datasets/street-centerlines/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=c36d828494cd44b5bd8b038be696c839) | External (City, Streets Dept.) |
| **Police Divisions**: made by dissolving police districts using the district-to-division list in `scripts/06_crime_data.py` (`DIVISIONS`) | Division layer | Edit the `DIVISIONS` list in script 06 | `docs/data/police_divisions.geojson` | Division list from <https://www.phillypolice.com/district/districts-list/> | External source, built by the project |
| **Police contacts** (captains, addresses, phones, emails; as of 2026-10-06) | Popups for districts, divisions, PSAs and stations | **Edit by hand:** `docs/data/police_contacts.json` (the one `docs/data` file meant to be hand-edited) | Same file | <https://www.phillypolice.com/district/districts-list/> | External (copied by hand from PPD's website) |

An older PowerShell pull of the same three Carto tables (`update-data.ps1`) was retired on 2026-10-16;
a copy is in `..\_archive\2026-10-16_retired_scripts\`.

## 5. Hand-placed map layers (no download script)

These were downloaded or exported by hand, so they now have editable raw copies in
`data/raw/reference/`. **Edit the raw copy, keep the file name, then run
`python scripts/07_publish_reference_layers.py`** to copy them into `docs/data/`.

### City of Philadelphia layers: `data/raw/reference/city/`

| Dataset (service name) | Raw file (edit here) | Processed file | Source link | Internal / External |
|---|---|---|---|---|
| **City Limits** (`City_Limits`) | `city/City_Limits.geojson` | `docs/data/City_Limits.geojson` | <https://opendataphilly.org/datasets/city-limits/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=405ec3da942d4e20869d4e1449a2be48) | External (City) |
| **City Council Districts 2024** (`Council_Districts_2024`) | `city/Council_Districts_2024.geojson` | `docs/data/Council_Districts_2024.geojson` | <https://opendataphilly.org/datasets/city-council-districts/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=1ba5a5d68f4a4c75806e78b1d9245924) | External (City) |
| **Police Stations** (`Police_Stations`) | `city/Police_Stations.geojson` | `docs/data/Police_Stations.geojson` | <https://opendataphilly.org/datasets/police-stations/> · [ArcGIS item](https://www.arcgis.com/home/item.html?id=7e522339d7c24e8ea5f2c7780291c315) | External (City / PPD) |
| **Neighborhood Advisory Committees** (`NeighborhoodAdvisoryCommittees`), service areas plus contacts | `city/NeighborhoodAdvisoryCommittees.geojson` | `docs/data/NeighborhoodAdvisoryCommittees.geojson` | [ArcGIS item](https://www.arcgis.com/home/item.html?id=d6e9e21e6c844fa5a94e928b39f02352) · [Data.gov listing](https://catalog.data.gov/dataset/neighborhood-advisory-committees-nacs). **Unsure** of the OpenDataPhilly page | External (City, Division of Housing & Community Development) |
| **NAC Offices** (`NAC_Offices`) | `city/NAC_Offices.geojson` | `docs/data/NAC_Offices.geojson` | [ArcGIS item](https://www.arcgis.com/home/item.html?id=f382d2b7d01c4ff494d41a82b5d17f4b). **Unsure**: possibly part of <https://opendataphilly.org/datasets/neighborhood-resources/> | External (City, DHCD) |

To re-download any of these, open the ArcGIS item (or OpenDataPhilly page), download
GeoJSON, and save it over the raw file with the same name.

### Temple University layers: `data/raw/reference/temple/`

All three are hosted in **Temple University's ArcGIS Online organization**. The item
pages show the owner. They are also referenced in the ArcGIS Pro project.

| Dataset (item title / service) | Raw file (edit here) | Processed file | Source link | Internal / External |
|---|---|---|---|---|
| **TU Building Footprints** (`all_campus_shapefile_updated`). Also exported to `ArcGIS Pro\community_engagement.gdb\TUBuildingsFootprints_Export` | `temple/TU_buildings.geojson` | `docs/data/TU_buildings.geojson` | [ArcGIS item](https://www.arcgis.com/home/item.html?id=f58968b65a9441b98c4498fc63d697bb) · service `https://services.arcgis.com/6fiE7QkLWSPMd0N5/arcgis/rest/services/all_campus_shapefile_updated/FeatureServer` | Internal (Temple University) |
| **TU Police Patrol Boundary** (`TU_Police_Patrol_Boundary_`): Main and HSC campuses | `temple/TU_police_boundary.geojson` | `docs/data/TU_police_boundary.geojson` | [ArcGIS item](https://www.arcgis.com/home/item.html?id=02b069ad743843d19752d4d632219a42) | Internal (Temple University) |
| **TU Police Stations** (`TU Police Stations`) | `temple/TU_Police_Stations.geojson` | `docs/data/TU_Police_Stations.geojson` | [ArcGIS item](https://www.arcgis.com/home/item.html?id=532177c23ea04c46868b3f0d90e4038b) | Internal (Temple University) |

### Project planning layers: `data/raw/reference/project/`

| Dataset | Raw file (edit here) | Processed file | Source / how it was made | Internal / External |
|---|---|---|---|---|
| **Potential Priority Impact Area and North Philly Partnership Area** (KML). The original source of the layers below. The area of focus was removed from both KML copies on 2026-10-16; the only full copy is in `data/private_app_files/` | `project/Potential Priority Impact Area and North Philly Partnership Area.kml` (copy of `ArcGIS Pro\source_data\…kml`; the `.lyrx` is there too) | Imported into `ArcGIS Pro\Potential Priority Impact Area and North Philly Partnership Area.gdb` (`Points`, `Polylines`, `Polygons`) | Exported from **Google My Maps** (the KML uses My Maps icons). **Unsure** who made the map; probably the requesting office or Temple staff | Internal (**Unsure**: confirm the map's author) |
| **Polygons of interest** (9 public planning areas: catchment areas, CHOICE neighborhoods, campus districts, NCSSD) | `project/Polygons_of_interest.geojson`, or edit the geometry in ArcGIS Pro: `community_engagement.gdb\Polygons_of_interest` and export to GeoJSON (keep the area of focus out) | `docs/data/Polygons_of_interest.geojson` (the app's public base plan) | KML → ArcGIS Pro: polylines converted with Feature To Polygon, merged with the KML polygons (`Polygons_Merge`) → `Polygons_of_interest` → GeoJSON. One name was later fixed by hand ("Line 1" → "CHOICE Neighborhood - North Central") | Internal (made by the project) |
| **Original Proposed Area of Focus** (the proposed outreach boundary; **private**) | `data/private_app_files/Original_Proposed_Area_of_Focus.geojson` | **Not published.** Loaded in the app with Load private files and added to the base plan | Cut out of the same Polygons of interest layer on 2026-10-16 | Internal (made by the project) |
| **Schools of Interest** (Duckrey, Bethune, Dunbar) | `project/Schools_of_Interest.geojson` | `docs/data/Schools_of_Interest.geojson` | The KML's `Points` layer, exported to GeoJSON | Internal (made by the project) |

## 5b. Community organizations (script 09)

| Dataset | Used for | Where to edit | Published file | Link | Internal / External |
|---|---|---|---|---|---|
| **FIRM CBO contact list** (`data/raw/north_philly_cbos_contacts.csv`) | Community Organizations layer (organizations marked "FIRM list") | **Edit the CSV**, then run `python scripts/09_community_orgs.py`. Addresses are placed with the OPA address file, then OpenStreetMap Nominatim, then the list's own coordinates | `docs/data/cbos.geojson` | (internal list) | Internal (FIRM) |
| **OpenStreetMap organizations** in the 8 priority ZIPs (community centers, social facilities, food banks, NGO/charity/association offices) via the Overpass API | More organizations for the same layer | Exclusion and category rules at the top of script 09 (`EXCLUDE_*`, `CATEGORIES`); review `data/processed/community_orgs/cbos_review.csv` | `docs/data/cbos.geojson` | <https://overpass-api.de/api/interpreter> · data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) | External (OpenStreetMap) |
| **Registered Community Organizations** (`Zoning_RCO`), features touching a priority ZIP | RCO layer: boundaries, meeting place, primary and alternate contacts, registration years. Contacts' home addresses are not published | Re-run script 09 | `docs/data/rcos.geojson` | <https://metadata.phila.gov/#home/representationdetails/55438ab59b989a05172d0d57/> · `https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services/Zoning_RCO/FeatureServer/0` | External (City Planning Commission) |

## 6. Live services the app calls (no local file)

| Service | Used for | Link | Internal / External |
|---|---|---|---|
| City `Street_Centerline` (live) | Street centerline layer and corner snapping | See §4 | External (City) |
| City `Vacant_Indicators_Bldg` (live) | Vacant building footprints inside the selected polygon | See §1 | External (City) |
| City boundary services (`Boundaries_District`, `Boundaries_PSA`, `Political_Wards`, `Political_Divisions`, `Zipcodes_Poly`) | Fallback only, when a `docs/data` file is missing | See §3–4 | External (City) |
| OpenStreetMap through the Overpass API | "Places of interest" layer (businesses, worship, schools, health, civic, parks) | <https://overpass-api.de/api/interpreter> (backup: `overpass.private.coffee`) · data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) | External (OpenStreetMap) |
| Basemaps: OpenStreetMap tiles ("Light gray", "OpenStreetMap"), Esri World Topographic, Esri World Imagery | Background maps | <https://tile.openstreetmap.org> · <https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer> · <https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer> | External (OSM, Esri) |
| Philadelphia Atlas property pages, Google Maps directions and Street View | Links in popups (open in a new tab, no data loaded) | <https://property.phila.gov> · <https://www.google.com/maps> | External |

## 7. Not used (kept for reference)

`..\_archive\2026-09-24_original_working_data\` holds older copies:
a **partial** `OPA_PROPERTIES_PUBLIC.csv` (34 MB; don't use it),
`LI_BUILDING_FOOTPRINTS.csv`, `Police_Boundaries_District.csv`, the 2024 tract
shapefile zip, and outputs of the old model. The old `philly_acs_tracts.py` there
has a Census API key typed into it, so don't share that folder.
