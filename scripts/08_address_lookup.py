"""
08_address_lookup.py

Builds the address lookup the web app uses to place a raw member export
(ID, Status, Address) on the map INSIDE THE BROWSER, so members' addresses are
never sent anywhere. The lookup holds only public City data: every address
point in the OPA property file.

Input   data/raw/OPA_PROPERTIES_PUBLIC.csv
Output  docs/data/addresses/<first letter of street name>.json, one file per
        letter or digit, loaded only when an address needs it:

        { "SPENCER": [[dir, suffix, house_no, lon_e5, lat_e5, zip], ...], ... }

        dir/suffix as OPA writes them ("W", "AVE"), lon/lat as integers in
        1e-5 degrees (about 1 m), zip as 5 digits.

Run from the repo root (only when OPA is refreshed):
    python scripts/08_address_lookup.py
"""

import json
from collections import defaultdict

import geopandas as gpd
import pandas as pd

from common import OPA_CSV, WEB_DATA

OUT = WEB_DATA / "addresses"


def main():
    cols = ["house_number", "street_direction", "street_name", "street_designation", "zip_code", "shape"]
    opa = pd.read_csv(OPA_CSV, usecols=lambda c: c.lower() in cols, dtype=str, low_memory=False)
    opa.columns = [c.lower() for c in opa.columns]
    shape = opa["shape"].fillna("").str.replace(r"^SRID=\d+;", "", regex=True)
    ok = shape.str.upper().str.startswith("POINT") & ~shape.str.upper().str.contains("EMPTY")
    opa = opa[ok].copy()
    pts = gpd.GeoSeries.from_wkt(shape[ok].to_numpy(dtype=object), crs=2272).to_crs(4326)
    f = lambda c: opa[c].fillna("").str.upper().str.strip()
    num = pd.to_numeric(f("house_number").str.replace(r"\.0$", "", regex=True), errors="coerce")
    table = pd.DataFrame({"name": f("street_name"), "dir": f("street_direction"), "suf": f("street_designation"),
                          "num": num, "lon": (pts.x.to_numpy() * 1e5).round(), "lat": (pts.y.to_numpy() * 1e5).round(),
                          "zip": f("zip_code").str[:5]})
    table = table[(table["name"] != "") & table["num"].notna()]
    table = table.drop_duplicates(["name", "dir", "suf", "num"])      # one point per address
    table["num"] = table["num"].astype(int)
    table[["lon", "lat"]] = table[["lon", "lat"]].astype(int)

    groups = defaultdict(dict)
    for name, g in table.groupby("name", sort=True):
        key = name[0] if name[0].isalnum() else "_"
        groups[key][name] = g[["dir", "suf", "num", "lon", "lat", "zip"]].values.tolist()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    total = 0
    for key, streets in sorted(groups.items()):
        p = OUT / f"{key}.json"
        p.write_text(json.dumps(streets, separators=(",", ":")))
        total += p.stat().st_size
    print(f"{len(table):,} addresses on {table['name'].nunique():,} streets -> docs/data/addresses/ "
          f"({len(groups)} files, {total / 1024**2:,.1f} MB, largest "
          f"{max(p.stat().st_size for p in OUT.glob('*.json')) / 1024**2:,.1f} MB)")


if __name__ == "__main__":
    main()
