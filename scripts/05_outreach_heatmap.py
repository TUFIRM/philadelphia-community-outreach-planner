"""
05_outreach_heatmap.py

Turns the outreach program member list into a private file the web app can
load from your computer. Nothing from the member list is published.

The member file holds people's home addresses, so it NEVER goes into the repo.
This script:
    1. reads data/raw/outreach/gateway_clients.csv. Two layouts work:
         standard intake (see templates/outreach_intake_template.csv):
             ID, Status, Street, Unit, City, State, ZIP
         older exports:  ID, Status, Address   (one free-text address)
    2. matches addresses to the City's OPA property file on this computer
       (no data leaves your machine); anything left over goes to the free
       U.S. Census batch geocoder (only street, city, state and ZIP are sent)
    3. fills in a missing ZIP from the ZIP polygon the member's point falls in
    4. places members at the middle of their street block (default), or on a
       ~250 m grid with --grid. Members outside the city keep their cell center.
    5. writes ONE private file (never copied into docs/):
         data/private_app_files/outreach_private.csv
           kind=map rows: lat, lon, cell (0 = street block), counts by status
           kind=zip rows: zip, counts by status
       Open the planner and use "Load private files" to view it.

The geocoded point file stays in data/processed/outreach/ (git-ignored).

Run from the repo root:
    python scripts/05_outreach_heatmap.py
    python scripts/05_outreach_heatmap.py --grid      # coarser ~250 m cells
"""

import argparse
import io
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import geopandas as gpd

from common import OPA_CSV, OUTREACH_CSV, OUTREACH_DIR, PRIVATE_DIR, PROCESSED, WEB_DATA

GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
CITY_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
GRID_DEG = 0.0025            # ~250 m cells; bigger = blurrier map and rougher polygon counts
MIN_MEMBERS_PER_CELL = 1     # 1 = show every cell (decided 2026-10-16: the file is private, loaded only locally)
STREETS_GPKG = PROCESSED / "crime" / "street_centerline.gpkg"   # shared with scripts/06
CRS_FT = 2272                # PA State Plane South, feet
# Spellings that differ between how people write addresses and how OPA stores them
WORDS = {
    "STREET": "ST", "STR": "ST", "AVENUE": "AVE", "AV": "AVE", "ROAD": "RD", "BOULEVARD": "BLVD",
    "DRIVE": "DR", "LANE": "LN", "PLACE": "PL", "TERRACE": "TER", "COURT": "CT", "PARKWAY": "PKWY",
    "CIRCLE": "CIR", "SQUARE": "SQ", "HIGHWAY": "HWY", "PIKE": "PIKE", "WAY": "WAY",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "FIRST": "1ST", "SECOND": "2ND", "THIRD": "3RD", "FOURTH": "4TH", "FIFTH": "5TH", "SIXTH": "6TH",
    "SEVENTH": "7TH", "EIGHTH": "8TH", "NINTH": "9TH", "TENTH": "10TH",
}
SUFFIXES = {"ST", "AVE", "RD", "BLVD", "DR", "LN", "PL", "TER", "CT", "PKWY", "CIR", "SQ", "HWY", "PIKE", "WAY", "ALY", "WALK", "ROW"}
DIRECTIONS = {"N", "S", "E", "W"}
STATUS_COLUMNS = {"Active": "active", "Disengaged": "disengaged",
                  "Milestone complete": "milestone", "Inquiry": "inquiry"}
UNIT_RE = r"(\b(apt|apartment|unit|fl|floor|rm|room|ste|suite)\b\.?|#)\s*\w*.*$"


def clean_zip(z):
    """'19141', '19141-2203', 19141.0 -> '19141'; anything else -> ''"""
    m = re.search(r"(?<!\d)(\d{5})(?:-?\d{4})?(?!\d)", str(z or "").replace(".0", ""))
    return m.group(1) if m else ""


def clean_street(s):
    """Keep house number and street; drop units and stray punctuation. No house number -> ''.
    Text before the house number ("Paseo Verde 1950 N 9th St", "Northeast 6347 Calvert St") is
    dropped; P.O. boxes and values without a street name (phone numbers) give ''."""
    s = re.sub(r"\s+", " ", str(s or "").replace(",", " ")).strip()
    if re.search(r"\bP\.?\s?O\.?\s?BOX|\bPOB\b|POBOX", s, flags=re.I):
        return ""
    if not re.match(r"^\d", s):
        m = re.search(r"\b\d{1,5}[A-Za-z]?\s+[A-Za-z]", s)
        s = s[m.start():] if m else ""
    s = re.sub(UNIT_RE, " ", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -.")
    return s if re.match(r"^\d", s) and len(re.findall(r"[A-Za-z]", s)) >= 2 else ""


def split_address(raw):
    """'4131 parrish street apt 2 philadelphia pa 19104' -> ('4131 parrish street', '19104')

    The ZIP is the last 5-digit number that is not the house number, so
    'PA19104', '19104-2203' and suburban ZIPs are found too."""
    s = str(raw or "").strip()
    found = [m for m in re.finditer(r"(?<!\d)(\d{5})(?:-\d{4})?(?!\d)", s)
             if m.start() > 0 or s[m.end():].strip() == ""]      # a leading 5-digit number is a house number
    zipcode = found[-1].group(1) if found else ""
    if found:
        s = s[:found[-1].start()] + " " + s[found[-1].end():]
    s = re.sub(r"\b(philadelphia|phila|phl)\b|\bpa\b|\bpenn(sylvania)?\b", " ", s, flags=re.I)
    return clean_street(s), zipcode


def read_members(path):
    """One row per member: status, street, city, state, zip (all strings).
    Excel/Google exports work as-is: UTF-8 with or without a BOM (or Windows-1252), and quoted
    addresses that run over several lines."""
    try:
        src = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    except UnicodeDecodeError:
        src = pd.read_csv(path, dtype=str, encoding="cp1252").fillna("")
    cols = {c.strip().lower(): c for c in src.columns}
    df = pd.DataFrame({"status": src[cols["status"]].str.strip().replace("", "Unknown")}) if "status" in cols \
        else pd.DataFrame({"status": ["Unknown"] * len(src)})
    if "street" in cols:                       # standard intake
        get = lambda name: src[cols[name]].str.strip() if name in cols else pd.Series("", index=src.index)
        df["street"] = get("street").map(clean_street)
        df["city"] = get("city")
        df["state"] = get("state").str.upper()
        df["zip"] = get("zip").map(clean_zip)
        layout = "standard intake (Street, Unit, City, State, ZIP)"
    elif "address" in cols:                    # older one-field export
        df[["street", "zip"]] = src[cols["address"]].apply(lambda a: pd.Series(split_address(a)))
        df["city"], df["state"] = "", ""
        layout = "older export (one Address field)"
    else:
        raise ValueError(f"{path.name} needs Street/City/State/ZIP columns or an Address column. Found: {list(src.columns)}")
    print(f"Member file: {len(df):,} rows, {layout}")
    return df


def in_philly(df):
    """True where the member's address is (or may be) in Philadelphia."""
    city = df["city"].str.upper().str.strip()
    return (df["zip"].str.startswith("191") | (df["zip"] == "")) & city.isin(["", "PHILADELPHIA", "PHILA", "PHL"])


def address_keys(street):
    """'1915 w spencer avenue' -> ['1915 W SPENCER AVE', '1915 W SPENCER', '1915 SPENCER AVE', '1915 SPENCER']
    Most specific first; looser keys catch a missing suffix or direction."""
    words = re.sub(r"[^A-Z0-9 ]", " ", str(street).upper()).split()
    words = [WORDS.get(w, w) for w in words]
    if len(words) < 2 or not words[0][0].isdigit():
        return []
    num = re.sub(r"\D.*$", "", words[0])            # '1915A' -> '1915'
    rest = words[1:]
    dirn = rest[0] if rest and rest[0] in DIRECTIONS and len(rest) > 1 else ""
    if dirn:
        rest = rest[1:]
    suffix = rest[-1] if len(rest) > 1 and rest[-1] in SUFFIXES else ""
    name = " ".join(rest[:-1] if suffix else rest)
    keys = [f"{num} {dirn} {name} {suffix}", f"{num} {dirn} {name}", f"{num} {name} {suffix}", f"{num} {name}"]
    return list(dict.fromkeys(" ".join(k.split()) for k in keys))


def opa_lookup():
    """One point (and ZIP) per address key from the City's OPA property file."""
    if not OPA_CSV.exists():
        print(f"OPA file not found ({OPA_CSV}); using only the Census geocoder.")
        return {}
    cols = ["house_number", "street_direction", "street_name", "street_designation", "zip_code", "shape"]
    opa = pd.read_csv(OPA_CSV, usecols=lambda c: c.lower() in cols, dtype=str, low_memory=False)
    opa.columns = [c.lower() for c in opa.columns]
    shape = opa["shape"].fillna("").str.replace(r"^SRID=\d+;", "", regex=True)
    opa = opa[shape.str.upper().str.startswith("POINT") & ~shape.str.upper().str.contains("EMPTY")].copy()
    pts = gpd.GeoSeries.from_wkt(shape[opa.index].to_numpy(dtype=object), crs=2272).to_crs(4326)
    opa["lon"], opa["lat"] = pts.x.to_numpy(), pts.y.to_numpy()
    f = lambda c: opa[c].fillna("").str.upper().str.strip() if c in opa else pd.Series("", index=opa.index)
    num = f("house_number").str.replace(r"\.0$", "", regex=True)
    d, n, s = f("street_direction"), f("street_name"), f("street_designation")
    z = f("zip_code").str[:5]
    lookup = {}
    for k in [num + " " + d + " " + n + " " + s, num + " " + d + " " + n, num + " " + n + " " + s, num + " " + n]:
        k = k.str.split().str.join(" ")
        for key, lon, lat, zz in zip(k, opa["lon"], opa["lat"], z):
            lookup.setdefault(key, (lon, lat, zz))
    print(f"OPA address lookup: {len(lookup):,} address keys")
    return lookup


def match_opa(df, lookup):
    """Philadelphia addresses only. A match whose OPA ZIP differs from the member's ZIP is skipped
    (left for the Census geocoder) so a same-named street elsewhere is never used."""
    out, zip_mismatch = {}, 0
    for i, street, zipcode in zip(df.index, df["street"], df["zip"]):
        for k in address_keys(street):
            if k in lookup:
                lon, lat, z = lookup[k]
                if zipcode and z and z != zipcode:
                    zip_mismatch += 1
                else:
                    out[i] = (lon, lat)
                break
    if zip_mismatch:
        print(f"  {zip_mismatch:,} OPA matches skipped because the ZIP disagreed")
    res = pd.DataFrame.from_dict(out, orient="index", columns=["lon", "lat"])
    res["type"] = "OPA"
    return res


def geocode(df):
    rows = df[df["street"] != ""]
    philly = in_philly(rows)
    payload = pd.DataFrame({"id": rows.index, "street": rows["street"],
                            "city": rows["city"].where(rows["city"] != "", np.where(philly, "Philadelphia", "")),
                            "state": rows["state"].where(rows["state"] != "", np.where(philly | rows["zip"].str.startswith("19"), "PA", "")),
                            "zip": rows["zip"]})
    results = []
    for start in range(0, len(payload), 5000):
        chunk = payload.iloc[start:start + 5000]
        buf = io.StringIO()
        chunk.to_csv(buf, header=False, index=False)
        print(f"Geocoding {start + 1}-{start + len(chunk)} of {len(payload)} ...")
        r = requests.post(GEOCODER, timeout=600,
                          files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
                          data={"benchmark": "Public_AR_Current"})
        r.raise_for_status()
        res = pd.read_csv(io.StringIO(r.text), header=None, dtype=str,
                          names=["id", "input", "match", "type", "matched", "coords", "tiger", "side"])
        results.append(res)
    res = pd.concat(results)
    res = res[res["match"] == "Match"].copy()
    xy = res["coords"].str.split(",", expand=True).astype(float)
    res["lon"], res["lat"] = xy[0], xy[1]
    res["id"] = res["id"].astype(int)
    return res.set_index("id")[["lon", "lat", "type"]]


def fill_zip_from_map(points):
    """Members placed on the map but with no ZIP in their address get the ZIP polygon they fall in."""
    zfile = WEB_DATA / "zip_codes.geojson"
    need = points["lon"].notna() & (points["zip"] == "")
    if not zfile.exists() or not need.any():
        return
    zips = gpd.read_file(zfile)[["code", "geometry"]].to_crs(4326)
    pts = gpd.GeoDataFrame(points[need], crs=4326,
                           geometry=gpd.points_from_xy(points.loc[need, "lon"], points.loc[need, "lat"]))
    hit = gpd.sjoin(pts, zips, how="left", predicate="within")
    hit = hit[~hit.index.duplicated()]
    points.loc[need, "zip"] = hit["code"].map(lambda v: str(int(v)) if pd.notna(v) else "")
    print(f"ZIP filled from map location: {(points.loc[need, 'zip'] != '').sum():,} of {need.sum():,}"
          f" (the rest are outside Philadelphia's ZIP polygons)")


def street_centerlines():
    """City street centerline segments (feet), cached in data/processed/crime/ like scripts/06."""
    if STREETS_GPKG.exists():
        return gpd.read_file(STREETS_GPKG)
    print("Downloading street centerlines (Street_Centerline) ...")
    feats, offset = [], 0
    while True:
        r = requests.get(f"{CITY_GIS}/Street_Centerline/FeatureServer/0/query", timeout=300, params={
            "where": "1=1", "outFields": "objectid,seg_id", "outSR": 4326, "f": "geojson",
            "orderByFields": "objectid", "resultOffset": offset, "resultRecordCount": 2000})
        r.raise_for_status()
        batch = r.json().get("features", [])
        feats += batch
        offset += len(batch)
        if len(batch) < 2000:
            break
    st = gpd.GeoDataFrame.from_features(feats, crs=4326)
    st = st[st.geometry.notna() & ~st.geometry.is_empty].copy()
    st["seg_id"] = st["seg_id"].astype("int64")
    st = st.to_crs(CRS_FT)[["seg_id", "geometry"]]
    STREETS_GPKG.parent.mkdir(parents=True, exist_ok=True)
    st.to_file(STREETS_GPKG, driver="GPKG")
    print(f"  {len(st):,} segments")
    return st


def by_status(df, keys):
    df = df.assign(col=df["status"].map(STATUS_COLUMNS).fillna("other"))
    t = df.pivot_table(index=keys, columns="col", values="status", aggfunc="size", fill_value=0)
    t["total"] = t.sum(axis=1)
    return t


def grid_cells(placed):
    placed = placed.assign(gx=np.floor(placed["lon"] / GRID_DEG).astype(int),
                           gy=np.floor(placed["lat"] / GRID_DEG).astype(int))
    grid = by_status(placed, ["gx", "gy"])
    kept = grid[grid["total"] >= MIN_MEMBERS_PER_CELL].reset_index()
    kept["lon"] = ((kept["gx"] + 0.5) * GRID_DEG).round(5)
    kept["lat"] = ((kept["gy"] + 0.5) * GRID_DEG).round(5)
    kept["cell"] = GRID_DEG
    print(f"Heat map: {len(kept):,} grid cells, {int(kept['total'].sum()):,} members "
          f"({int(grid['total'].sum() - kept['total'].sum()):,} in cells under {MIN_MEMBERS_PER_CELL} left out)")
    return kept


def street_blocks(placed):
    """Each member at the midpoint of the nearest street segment (a block), never the house itself.
    The City's centerlines stop at the city line, so members outside it keep their grid-cell center."""
    st = street_centerlines()
    pts = gpd.GeoDataFrame(placed, crs=4326, geometry=gpd.points_from_xy(placed["lon"], placed["lat"])).to_crs(CRS_FT)
    city = WEB_DATA / "City_Limits.geojson"
    if city.exists():
        limits = gpd.read_file(city).to_crs(CRS_FT).geometry.union_all()
        inside = pts.within(limits)
    else:
        inside = pd.Series(True, index=pts.index)
    near = gpd.sjoin_nearest(pts[inside], st, how="left", distance_col="ft")
    near = near[~near.index.duplicated()]
    blocks = by_status(near, ["seg_id"]).reset_index()
    mid = st.set_index("seg_id").geometry.interpolate(0.5, normalized=True).to_crs(4326)
    mid = mid[~mid.index.duplicated()]
    blocks["lon"] = blocks["seg_id"].map(mid.x).round(5)
    blocks["lat"] = blocks["seg_id"].map(mid.y).round(5)
    outside = grid_cells(placed[~inside.to_numpy()]) if (~inside).any() else blocks.iloc[0:0]
    out = pd.concat([blocks, outside], ignore_index=True).fillna(0)
    out["cell"] = 0               # 0 tells the app these are points, not grid cells
    far = int((near["ft"] > 150).sum())
    print(f"Street blocks: {len(blocks):,} blocks, {int(blocks['total'].sum()):,} members in Philadelphia"
          + (f" ({far} more than 150 ft from a street)" if far else "")
          + f"; {int((~inside).sum())} members outside the city kept at their ~250 m cell center")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--grid", action="store_true",
                    help="use ~250 m grid cells instead of street blocks")
    ap.add_argument("--input", type=Path, default=OUTREACH_CSV,
                    help="member export to read (default: data/raw/outreach/gateway_clients.csv)")
    args = ap.parse_args()

    if not args.input.exists():
        raise FileNotFoundError(f"Member export not found (it stays out of git):\n{args.input}")
    df = read_members(args.input)

    philly = df[(df["street"] != "") & in_philly(df)]
    opa_hits = match_opa(philly, opa_lookup())
    print(f"Matched to OPA addresses: {len(opa_hits):,} of {len(philly):,} Philadelphia addresses")
    rest = df[(df["street"] != "") & ~df.index.isin(opa_hits.index)]
    census_hits = geocode(rest) if len(rest) else pd.DataFrame(columns=["lon", "lat", "type"])
    print(f"Matched by Census geocoder: {len(census_hits):,} of {len(rest):,} left over")
    points = df.join(pd.concat([opa_hits, census_hits]), how="left")
    fill_zip_from_map(points)
    points.drop(columns="street").to_csv(OUTREACH_DIR / "outreach_geocoded_private.csv")

    placed = points.dropna(subset=["lon"]).copy()
    print(f"\nMembers: {len(df):,}   placed at an address: {len(placed):,}   "
          f"no street address: {(df['street'] == '').sum():,}   "
          f"address not matched: {((df['street'] != '') & points['lon'].isna()).sum():,}")

    # ---- map rows: street blocks (default) or ~250 m grid ----
    out = (grid_cells(placed) if args.grid else street_blocks(placed)).assign(kind="map")

    # ---- ZIP rows (includes members we could only place by ZIP) ----
    byzip = by_status(points[points["zip"] != ""], ["zip"]).reset_index().assign(kind="zip")
    print(f"ZIP counts: {len(byzip):,} ZIP codes, {int(byzip['total'].sum()):,} members")
    print(f"No ZIP at all (not in the ZIP table): {(points['zip'] == '').sum():,}")

    statuses = [c for c in ["active", "disengaged", "milestone", "inquiry", "other"]
                if c in out.columns or c in byzip.columns]
    both = pd.concat([out, byzip], ignore_index=True).reindex(
        columns=["kind", "lat", "lon", "cell", "zip", "total"] + statuses)
    both[["total"] + statuses] = both[["total"] + statuses].fillna(0).astype(int)
    dest = PRIVATE_DIR / "outreach_private.csv"
    both.to_csv(dest, index=False)
    print(f"\nPrivate file: {dest}")
    print(f"  {len(out):,} map rows, {len(byzip):,} ZIP rows. Load it in the app with Load private files.")

    # Older versions published these; make sure nothing is left in docs/ to push.
    for old in ("outreach_heat.csv", "outreach_by_zip.csv"):
        if (WEB_DATA / old).exists():
            (WEB_DATA / old).unlink()
            print(f"  removed docs/data/{old} (outreach data is no longer published)")


if __name__ == "__main__":
    main()
