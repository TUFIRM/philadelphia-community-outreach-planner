"""
update_data.py

Pulls the newest public City and Census data, rebuilds what depends on it,
checks everything, and (with --push) commits and pushes docs/data to GitHub.
Private data is never touched: outreach members and the area of focus stay
in data/private_app_files/ and are loaded in the app by hand.

    python scripts/update_data.py                # monthly: crime + boundary layers, then check
    python scripts/update_data.py --push         # ...and commit + push if every check passes
    python scripts/update_data.py --all --push   # also re-download OPA, footprints and vacancy,
                                                 # rebuild ACS tracts, building model, address lookup

Steps (in order; each only when selected):
    --raw   download OPA_PROPERTIES_PUBLIC.csv, LI_BUILDING_FOOTPRINTS.geojson and
            Vacant_Indicators_Bldg.geojson into data/raw/ (the old file is kept until the new
            one is complete)
    --acs   scripts/01 (new ACS 5-year release, usually each December)
    --model scripts/02, 03 and 08 (after --raw or --acs)
    boundaries  scripts/04          crime  scripts/06          (skip with --no-crime / --no-boundaries)
    check   scripts/check_data.py; stops here if anything FAILs
    --push  git add docs/data, commit "Data refresh YYYY-MM-DD", push (only if something changed)

Run from the repo root.
"""

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests

from common import FOOTPRINTS_GEOJSON, OPA_CSV, REPO, VACANT_GEOJSON

PY = sys.executable
SCRIPTS = REPO / "scripts"
OPA_URL = "https://opendata-downloads.s3.amazonaws.com/opa_properties_public.csv"
CITY_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"


def run(script, *args):
    print(f"\n=== {script} {' '.join(args)}".rstrip(), flush=True)
    subprocess.run([PY, str(SCRIPTS / script), *args], cwd=REPO, check=True)


def download_file(url, dest):
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.replace(dest)
    print(f"  {dest.name}: {dest.stat().st_size / 1024**2:,.0f} MB")


def download_layer(service, dest, page=2000):
    """Every feature of a City ArcGIS layer, written to GeoJSON a page at a time."""
    tmp = dest.with_suffix(dest.suffix + ".part")
    url = f"{CITY_GIS}/{service}/FeatureServer/0/query"
    n, offset = 0, 0
    with open(tmp, "w", encoding="utf-8") as f:
        f.write('{"type":"FeatureCollection","features":[')
        while True:
            r = requests.get(url, timeout=300, params={
                "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
                "orderByFields": "objectid", "resultOffset": offset, "resultRecordCount": page})
            r.raise_for_status()
            feats = r.json().get("features", [])
            for feat in feats:
                f.write(("," if n else "") + json.dumps(feat, separators=(",", ":")))
                n += 1
            offset += len(feats)
            if len(feats) < page:
                break
            if offset % 50000 < page:
                print(f"  {service}: {offset:,} features ...", flush=True)
        f.write("]}")
    if not n:
        tmp.unlink()
        raise RuntimeError(f"{service} returned no features; kept the old {dest.name}")
    tmp.replace(dest)
    print(f"  {dest.name}: {n:,} features, {dest.stat().st_size / 1024**2:,.0f} MB")


def git(*args):
    return subprocess.run(["git", "-c", f"safe.directory={REPO.as_posix()}", *args], cwd=REPO,
                          check=True, capture_output=True, text=True).stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="--raw + --acs + --model, plus crime and boundaries")
    ap.add_argument("--raw", action="store_true", help="re-download OPA, building footprints and vacancy")
    ap.add_argument("--acs", action="store_true", help="re-download ACS tract data (scripts/01)")
    ap.add_argument("--model", action="store_true", help="rebuild the building model and address lookup")
    ap.add_argument("--no-crime", action="store_true", help="skip scripts/06")
    ap.add_argument("--no-boundaries", action="store_true", help="skip scripts/04")
    ap.add_argument("--push", action="store_true", help="commit and push docs/data if every check passes")
    a = ap.parse_args()
    if a.all:
        a.raw = a.acs = a.model = True
    if a.raw:
        a.model = True

    if a.raw:
        print("\n=== downloading raw City data into data/raw/")
        download_file(OPA_URL, OPA_CSV)
        download_layer("LI_BUILDING_FOOTPRINTS", FOOTPRINTS_GEOJSON)
        download_layer("Vacant_Indicators_Bldg", VACANT_GEOJSON)
    if a.acs:
        run("01_download_acs_tracts.py")
    if a.model:
        run("02_build_building_model.py")
        run("03_prepare_web_data.py")
        run("08_address_lookup.py")
    if not a.no_boundaries:
        run("04_download_reference_layers.py")
    if not a.no_crime:
        run("06_crime_data.py")

    print("\n=== check_data.py", flush=True)
    check = subprocess.run([PY, str(SCRIPTS / "check_data.py")], cwd=REPO)
    if check.returncode != 0:
        sys.exit("A check FAILED: nothing was committed. Fix it, then rerun with --push.")

    if a.push:
        git("add", "--", "docs/data")
        if not git("diff", "--cached", "--name-only").strip():
            print("\nNo data changed; nothing to push.")
            return
        git("commit", "-m", f"Data refresh {date.today().isoformat()}")
        git("push")
        print("\nPushed. GitHub Pages republishes in a minute or two.")
    else:
        print("\nChecks passed. Review `git status`, or rerun with --push to commit and push docs/data.")


if __name__ == "__main__":
    main()
