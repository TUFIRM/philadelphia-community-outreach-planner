"""
Shared paths and small helpers for every pipeline script.

Folder layout (relative to the repo root):

    data/raw/          source downloads you put here by hand (not in git)
    data/processed/    everything the scripts create (not in git)
    docs/              the web app GitHub Pages serves
    docs/data/         small files the web app loads (in git)

Big source files can live somewhere else (for example the S: drive).
Point the scripts at that folder by setting PLANNER_DATA_DIR in a .env file:

    PLANNER_DATA_DIR=S:/Space Management/Projects/GIS - Community Engagement Tracker/data

That folder then needs the same raw/ and processed/ subfolders.
"""

import json
import os
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_env(path=REPO / ".env"):
    """Read KEY=VALUE lines from .env into os.environ (no extra package needed)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

DATA_DIR = Path(os.environ.get("PLANNER_DATA_DIR", REPO / "data"))
RAW = DATA_DIR / "raw"
PROCESSED = DATA_DIR / "processed"
WEB_DATA = REPO / "docs" / "data"

ACS_DIR = PROCESSED / "acs"
MODEL_DIR = PROCESSED / "building_model"
OUTREACH_DIR = PROCESSED / "outreach"
# Files the app loads from your computer with "Load private files" (outreach CSV, proposed plan).
# Never copied into docs/ and never published.
PRIVATE_DIR = DATA_DIR / "private_app_files"

# ACS 5-year release in use (2024 = the 2020-2024 estimates). Read from docs/data/acs_meta.json,
# which scripts/01 writes, so a new release needs no code change: update_data.py finds it,
# sets ACS_YEAR for the run, and script 01 records it. Set ACS_YEAR in .env only to override.
ACS_META = WEB_DATA / "acs_meta.json"
ACS_WEB_CSV = "philly_tracts_acs.csv"      # name of the tract file in docs/data (no year in it)


def _acs_year(default=2024):
    if os.environ.get("ACS_YEAR"):
        return int(os.environ["ACS_YEAR"])
    try:
        return int(json.loads(ACS_META.read_text(encoding="utf-8"))["year"])
    except (OSError, ValueError, KeyError):
        return default


ACS_YEAR = _acs_year()

# Raw inputs (download these yourself, see README)
OPA_CSV = RAW / "OPA_PROPERTIES_PUBLIC.csv"
FOOTPRINTS_GEOJSON = RAW / "LI_BUILDING_FOOTPRINTS.geojson"
VACANT_GEOJSON = RAW / "Vacant_Indicators_Bldg.geojson"
OUTREACH_CSV = RAW / "outreach" / "gateway_clients.csv"
GQ_BUILDINGS_CSV = RAW / "group_quarters_buildings.csv"   # optional

# Outputs shared between scripts
TRACT_GPKG = ACS_DIR / f"philly_tracts_acs{ACS_YEAR}.gpkg"
TRACT_CSV = ACS_DIR / f"philly_tracts_acs{ACS_YEAR}.csv"
BUILDING_POINTS_GPKG = MODEL_DIR / "philly_building_points.gpkg"

for folder in (RAW, PROCESSED, ACS_DIR, MODEL_DIR, OUTREACH_DIR, PRIVATE_DIR, WEB_DATA):
    folder.mkdir(parents=True, exist_ok=True)


def publish(path, name=None):
    """Copy a finished file into docs/data so the web app can load it."""
    dest = WEB_DATA / (name or Path(path).name)
    shutil.copy2(path, dest)
    print(f"  published -> docs/data/{dest.name}  ({dest.stat().st_size / 1024**2:,.1f} MB)")
    return dest
