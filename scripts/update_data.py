"""
update_data.py - THE MONTHLY UPDATE. One command refreshes all public data, rebuilds the
demographic model when its inputs changed, checks everything, and (with --push) publishes.

Easiest: double-click "Run monthly update.bat" in the repo folder (it runs this with --push).
Or, from the repo folder:

    python scripts/update_data.py            # update + check, nothing published (to look first)
    python scripts/update_data.py --push     # update + check + commit + push (the monthly run)

What it does, in order (each step is skipped when there is nothing new):
    1. git pull                      (with --push) so you start from the published version
    2. Census ACS                    asks the Census API whether a newer 5-year release exists
                                     (one comes out each December) and downloads it (script 01)
    3. City property data            downloads OPA properties, building footprints and vacancy
                                     into data/raw/ when the City has published newer copies
    4. demographic model             scripts 02, 03, 08 when step 2 or 3 brought anything new
    5. boundaries, crime, layers     scripts 04 (police districts, ZIPs, wards, divisions),
                                     06 (crime, shootings, stops), 07 (hand-edited layers in
                                     data/raw/reference/), 09 (community organizations, RCOs)
    6. police stations               compares station phones with docs/data/police_contacts.json
    7. check_data.py                 nothing is pushed if any check FAILs
    8. push                          (with --push) commit docs/data and push; the site updates
                                     a minute or two later
At the end it prints what (if anything) needs a person, and appends a summary to
data/processed/update_history.txt.

Private data is never touched: outreach members and the area of focus stay in
data/private_app_files/ and are loaded in the app by hand.

Options
    --quick           crime and boundaries only (steps 1, 5 without 07/09, 7, 8; ~15 min)
    --force           re-download the City property data and rebuild the model even if unchanged
    --no-model        skip steps 2-4          --no-crime / --no-boundaries / --no-orgs   skip parts of 5
Time: about 1-1.5 hours when the model is rebuilt (most months), 15-30 minutes otherwise.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import requests

from common import ACS_YEAR, FOOTPRINTS_GEOJSON, OPA_CSV, PROCESSED, REPO, VACANT_GEOJSON, WEB_DATA

PY = sys.executable
SCRIPTS = REPO / "scripts"
OPA_URL = "https://opendata-downloads.s3.amazonaws.com/opa_properties_public.csv"
CITY_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
MODEL_MARK = PROCESSED / "building_model" / "built_for_acs_year.txt"   # which ACS release the model matches
ENV = dict(os.environ)
attention = []          # things a person has to do, printed at the end
done = []               # what this run changed


class StepFailed(Exception):
    pass


def run(script, *args):
    print(f"\n=== {script} {' '.join(args)}".rstrip(), flush=True)
    if subprocess.run([PY, str(SCRIPTS / script), *args], cwd=REPO, env=ENV).returncode != 0:
        raise StepFailed(script)


def soft(label, fn):
    """Run a step; on failure note it and carry on with the rest (the old files are kept)."""
    try:
        fn()
        return True
    except Exception as e:          # noqa: BLE001 - any failure: keep going, report at the end
        attention.append(f"{label} failed ({type(e).__name__}: {e}). The previous data was kept; "
                         f"rerun later (a City or Census service may have been down).")
        print(f"\n!!! {label} failed: {e}", flush=True)
        return False


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


def local_time(path):
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) if path.exists() else None


def remote_time_file(url):
    r = requests.head(url, timeout=60)
    r.raise_for_status()
    return parsedate_to_datetime(r.headers["Last-Modified"])


def remote_time_layer(service):
    info = requests.get(f"{CITY_GIS}/{service}/FeatureServer/0", params={"f": "json"}, timeout=60).json()
    ms = (info.get("editingInfo") or {}).get("dataLastEditDate") or (info.get("editingInfo") or {}).get("lastEditDate")
    return datetime.fromtimestamp(ms / 1000, timezone.utc) if ms else None


def git(*args):
    return subprocess.run(["git", "-c", f"safe.directory={REPO.as_posix()}", *args], cwd=REPO,
                          check=True, capture_output=True, text=True).stdout


# ---------------------------------------------------------------- steps
def newest_acs_year():
    """Newest ACS 5-year release the Census API answers for (None if none newer than ACS_YEAR)."""
    for y in range(date.today().year, ACS_YEAR, -1):
        r = requests.get(f"https://api.census.gov/data/{y}/acs/acs5", timeout=60)
        if r.status_code == 200:
            return y
    return None


def step_acs():
    y = newest_acs_year()
    if not y:
        print(f"\n=== Census ACS: {ACS_YEAR - 4}-{ACS_YEAR} is still the newest release", flush=True)
        return False
    print(f"\n=== Census ACS: new release {y - 4}-{y} found (using {ACS_YEAR - 4}-{ACS_YEAR})", flush=True)
    if not ENV.get("CENSUS_API_KEY"):
        attention.append(f"A new Census release (ACS {y - 4}-{y}) is out but .env has no CENSUS_API_KEY. "
                         "Get a free key (README, 'Taking over the project'), add it to .env and run the update again.")
        return False
    ENV["ACS_YEAR"] = str(y)
    try:
        run("01_download_acs_tracts.py")      # writes docs/data/acs_meta.json, which later runs read
    except StepFailed:
        del ENV["ACS_YEAR"]                   # keep using the release we have
        raise
    done.append(f"Census data updated to ACS {y - 4}-{y}")
    return True


def step_raw(force):
    """Download the City's property files that are newer than our copies. True if any changed."""
    changed = False
    for name, dest, remote, get in [
        ("OPA properties", OPA_CSV, lambda: remote_time_file(OPA_URL), lambda: download_file(OPA_URL, OPA_CSV)),
        ("Building footprints", FOOTPRINTS_GEOJSON, lambda: remote_time_layer("LI_BUILDING_FOOTPRINTS"),
         lambda: download_layer("LI_BUILDING_FOOTPRINTS", FOOTPRINTS_GEOJSON)),
        ("Vacant buildings", VACANT_GEOJSON, lambda: remote_time_layer("Vacant_Indicators_Bldg"),
         lambda: download_layer("Vacant_Indicators_Bldg", VACANT_GEOJSON)),
    ]:
        mine, theirs = local_time(dest), remote()
        if force or mine is None or theirs is None or theirs > mine:
            print(f"\n=== {name}: downloading (City copy {theirs:%Y-%m-%d}, ours "
                  f"{mine.date() if mine else 'missing'})" if theirs else f"\n=== {name}: downloading", flush=True)
            get()
            changed = True
        else:
            print(f"\n=== {name}: our copy is current ({mine:%Y-%m-%d})", flush=True)
    if changed:
        done.append("City property data downloaded")
    return changed


def step_model():
    run("02_build_building_model.py")
    run("03_prepare_web_data.py")
    run("08_address_lookup.py")
    MODEL_MARK.write_text(ENV.get("ACS_YEAR", str(ACS_YEAR)))
    done.append("demographic model rebuilt")


def step_police_stations():
    """Compare the City's station phones with police_contacts.json (captains can't be checked: see README)."""
    print("\n=== police stations: comparing phones with police_contacts.json", flush=True)
    contacts = json.loads((WEB_DATA / "police_contacts.json").read_text(encoding="utf-8-sig"))
    mine = contacts.get("districts") or {}
    r = requests.get(f"{CITY_GIS}/Police_Stations/FeatureServer/0/query", timeout=60,
                     params={"where": "1=1", "outFields": "dist_num,location,phone__", "returnGeometry": "false", "f": "json"})
    r.raise_for_status()
    digits = lambda s: "".join(ch for ch in str(s or "") if ch.isdigit())[-7:]
    diffs = []
    for feat in r.json().get("features", []):
        a = feat["attributes"]
        key = str(a.get("dist_num") or "").zfill(2)
        if key == "00":
            continue
        if key not in mine:
            diffs.append(f"district {key} ({a.get('location')}) has no entry")
        elif digits(a.get("phone__")) and digits(a.get("phone__")) != digits(mine[key].get("phone")):
            diffs.append(f"district {key}: City lists phone {a.get('phone__')}, we have {mine[key].get('phone')}")
    if diffs:
        attention.append("Police station details differ from the City's list - check phillypolice.com and update "
                         "docs/data/police_contacts.json: " + "; ".join(diffs))
    else:
        print("  all station phones match", flush=True)


def check():
    print("\n=== check_data.py", flush=True)
    out = subprocess.run([PY, str(SCRIPTS / "check_data.py")], cwd=REPO, env=ENV, capture_output=True, text=True)
    print(out.stdout, out.stderr, sep="", flush=True)
    for line in out.stdout.splitlines():
        if line.startswith("WARN") and "Fresh:" in line:
            attention.append(line[4:].strip())
    return out.returncode == 0


def log(status):
    lines = [f"{datetime.now():%Y-%m-%d %H:%M}  {status}"] + [f"    did: {d}" for d in done] + \
            [f"    needs a person: {a}" for a in attention]
    with open(PROCESSED / "update_history.txt", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--push", action="store_true", help="commit and push docs/data if every check passes")
    ap.add_argument("--quick", action="store_true", help="crime and boundaries only")
    ap.add_argument("--force", action="store_true", help="re-download City property data and rebuild the model")
    ap.add_argument("--no-model", action="store_true", help="skip the Census / property / model steps")
    ap.add_argument("--no-crime", action="store_true", help="skip scripts/06")
    ap.add_argument("--no-boundaries", action="store_true", help="skip scripts/04")
    ap.add_argument("--no-orgs", action="store_true", help="skip scripts/09")
    # older flags, kept so existing notes still work
    ap.add_argument("--all", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--raw", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--acs", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--model", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.all or a.raw or a.model:
        a.force = True
    started = datetime.now()

    if a.push:
        print("=== git pull", flush=True)
        try:
            git("pull", "--ff-only")
        except subprocess.CalledProcessError as e:
            sys.exit("git pull failed, so nothing was updated:\n" + (e.stderr or e.stdout or "") +
                     "\nSomeone may have changed files here or on GitHub. See README, 'Troubleshooting'.")

    if not (a.quick or a.no_model):
        new = {}
        soft("Census ACS check", lambda: new.__setitem__("acs", step_acs()))
        soft("City property download", lambda: new.__setitem__("raw", step_raw(a.force)))
        built_for = MODEL_MARK.read_text().strip() if MODEL_MARK.exists() else ""
        stale = built_for != ENV.get("ACS_YEAR", str(ACS_YEAR))
        if new.get("acs") or new.get("raw") or stale or a.force:
            soft("Demographic model (scripts 02, 03, 08)", step_model)
        else:
            print("\n=== demographic model: inputs unchanged, not rebuilt", flush=True)
    if not a.no_boundaries:
        soft("Boundary layers (script 04)", lambda: run("04_download_reference_layers.py"))
    if not a.no_crime:
        soft("Crime data (script 06)", lambda: run("06_crime_data.py"))
    if not a.quick:
        soft("Hand-edited layers (script 07)", lambda: run("07_publish_reference_layers.py"))
        if not a.no_orgs:
            soft("Community organizations (script 09)", lambda: run("09_community_orgs.py"))
        soft("Police station check", step_police_stations)

    ok = check()
    minutes = (datetime.now() - started).seconds // 60
    if not ok:
        log("CHECK FAILED - nothing published")
        print("\n" + "=" * 70 + f"\nA check FAILED ({minutes} min): nothing was committed or published.\n"
              "Read the FAIL lines above, fix the cause (README, 'Troubleshooting'), then run the update again.")
        for x in attention:
            print(f"  - {x}")
        sys.exit(1)

    status = "checks passed"
    if a.push:
        git("add", "--", "docs/data")
        if git("diff", "--cached", "--name-only").strip():
            git("commit", "-m", f"Data refresh {date.today().isoformat()}")
            git("push")
            status = "published"
        else:
            status = "nothing changed, nothing to publish"

    log(status)
    print("\n" + "=" * 70)
    print(f"DONE in {minutes} min: {status}.")
    if status == "published":
        print("The live site updates in a minute or two: "
              "https://tufirm.github.io/philadelphia-community-outreach-planner/")
    elif not a.push:
        print("Nothing was published (no --push). To publish, run: python scripts/update_data.py --push")
    for d in done:
        print(f"  did: {d}")
    if attention:
        print("\nNEEDS A PERSON:")
        for x in attention:
            print(f"  - {x}")
    else:
        print("\nNothing needs you this month.")


if __name__ == "__main__":
    main()
