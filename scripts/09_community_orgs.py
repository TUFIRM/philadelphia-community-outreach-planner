"""
09_community_orgs.py

Community organizations in Temple's 8 priority ZIP codes (19121, 19122, 19123,
19125, 19130, 19132, 19133, 19140), as two app layers that start switched off:

    docs/data/cbos.geojson   community-based organizations (points)
        - from the FIRM list data/raw/north_philly_cbos_contacts.csv, kept when its
          address is in a priority ZIP and placed at the address using the City's OPA
          address points, then OpenStreetMap (Nominatim) if OPA has no match
        - plus organizations found in OpenStreetMap inside the priority ZIPs
          (community centres, social facilities, NGO/charity/association offices,
          food banks) that are not already on the list
    docs/data/rcos.geojson   Registered Community Organizations (City Planning
        Commission boundaries, Zoning_RCO) that touch a priority ZIP

For review before publishing:
    data/processed/community_orgs/cbos_review.csv   every list entry and OSM find,
        with what happened to it (kept, outside the ZIPs, how it was located)

Run from the repo root:
    python scripts/09_community_orgs.py
"""

import json
import re
import time

import geopandas as gpd
import pandas as pd
import requests
from shapely.geometry import Point

from common import PROCESSED, RAW, WEB_DATA

PRIORITY_ZIPS = {"19121", "19122", "19123", "19125", "19130", "19132", "19133", "19140"}
CBO_CSV = RAW / "north_philly_cbos_contacts.csv"
OUT_DIR = PROCESSED / "community_orgs"
CITY_GIS = "https://services.arcgis.com/fLeGjb7u4uXqeF9q/arcgis/rest/services"
OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "Temple FIRM community outreach planner (firm@temple.edu)"}
PUBLISH_COLS = ["name", "type", "categories", "address", "zip", "phone", "email", "website", "contact_name", "contact_title", "source"]
# OpenStreetMap tags that mark community organizations (places of worship and schools are left out)
OSM_FILTERS = [
    'nwr["amenity"~"^(community_centre|social_facility|social_centre|food_bank)$"]',
    'nwr["office"~"^(ngo|association|charity|foundation|non_profit)$"]',
    'nwr["social_facility"]',
]


def priority_zips():
    z = gpd.read_file(WEB_DATA / "zip_codes.geojson").to_crs(4326)
    z["code"] = z["code"].astype(str)
    return z[z["code"].isin(PRIORITY_ZIPS)][["code", "geometry"]]


def zip_of_address(addr):
    m = re.findall(r"(?<!\d)(19\d{3})(?!\d)", str(addr))
    return m[0] if m else ""


def opa_points():
    """Address key -> (lon, lat) from the public OPA lookup built by scripts/08."""
    pts = {}
    for p in (WEB_DATA / "addresses").glob("*.json"):
        for name, rows in json.loads(p.read_text()).items():
            for d, s, num, lon, lat, z in rows:
                pts.setdefault(" ".join(f"{num} {d} {name} {s}".split()), (lon / 1e5, lat / 1e5))
                pts.setdefault(" ".join(f"{num} {d} {name}".split()), (lon / 1e5, lat / 1e5))
                pts.setdefault(" ".join(f"{num} {name}".split()), (lon / 1e5, lat / 1e5))
    return pts


WORDS = {"STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
         "BOULEVARD": "BLVD", "DRIVE": "DR", "LANE": "LN", "PLACE": "PL"}


def address_keys(street):
    w = [WORDS.get(x, x) for x in re.sub(r"[^A-Z0-9 ]", " ", street.upper()).split()]
    if len(w) < 2 or not w[0][0].isdigit():
        return []
    num = re.sub(r"\D.*$", "", w[0]).lstrip("0")
    rest = w[1:]
    keys = [[num, *rest], [num, *rest[:-1]] if len(rest) > 1 else None,
            [num, *(rest[1:] if rest[0] in {"N", "S", "E", "W"} else rest)]]
    return [" ".join(k) for k in keys if k]


def nominatim(addr):
    time.sleep(1.1)                                   # Nominatim usage policy: max 1 request a second
    r = requests.get(NOMINATIM, headers=UA, timeout=60, params={"q": addr, "format": "json", "limit": 1,
                                                                 "countrycodes": "us"})
    r.raise_for_status()
    j = r.json()
    return (float(j[0]["lon"]), float(j[0]["lat"])) if j else None


def load_list(zips, lookup):
    src = pd.read_csv(CBO_CSV, dtype=str).fillna("")
    rows = []
    for _, r in src.iterrows():
        addr = r["street_address"]
        z = zip_of_address(addr)
        street = re.split(r",", addr)[0]
        street = re.sub(r"\s*(#|\bSte\b|\bSuite\b|\bFl\b|\d+(st|nd|rd|th) Fl).*$", "", street, flags=re.I).strip()
        street = re.sub(r"^(\d+)-\d+\b", r"\1", street)          # 1628-30 N 15th St -> 1628 N 15th St
        hit = next((lookup[k] for k in address_keys(street) if k in lookup), None)
        how = "City address (OPA)"
        if hit is None:
            hit = nominatim(addr)
            how = "OpenStreetMap (Nominatim)"
        if hit is None and r["latitude"] and r["longitude"]:
            hit, how = (float(r["longitude"]), float(r["latitude"])), "coordinates in the list"
        lon, lat = hit if hit else (None, None)
        in_zip = bool(hit) and zips.contains(Point(lon, lat)).any()
        rows.append({"name": r["name"], "type": r["type"], "address": addr, "zip": z, "phone": r["phone"],
                     "email": r["email"], "website": r["website"], "contact_name": r["contact_name"],
                     "contact_title": r["contact_title"], "source": "FIRM list", "lon": lon, "lat": lat,
                     "located_by": how if hit else "not located",
                     "result": "kept" if (z in PRIORITY_ZIPS or in_zip) else "left out: outside the priority ZIPs"})
    return pd.DataFrame(rows)


def osm_finds(zips):
    w, s, e, n = zips.total_bounds
    q = "[out:json][timeout:120];(" + "".join(f"{f}({s},{w},{n},{e});" for f in OSM_FILTERS) + ");out center tags;"
    r = requests.post(OVERPASS, data={"data": q}, headers=UA, timeout=180)
    r.raise_for_status()
    out = []
    for el in r.json().get("elements", []):
        t = el.get("tags", {})
        name = t.get("name", "").strip()
        lon, lat = (el.get("lon"), el.get("lat")) if "lon" in el else (el.get("center", {}).get("lon"), el.get("center", {}).get("lat"))
        if not name or lon is None:
            continue
        hit = zips[zips.contains(Point(lon, lat))]
        if hit.empty:
            continue
        kind = t.get("social_facility") or t.get("amenity") or t.get("office") or ""
        street = " ".join(x for x in [t.get("addr:housenumber", ""), t.get("addr:street", "")] if x)
        out.append({"name": name, "type": kind.replace("_", " ").title(), "address": street,
                    "zip": hit.iloc[0]["code"],          # the priority ZIP it sits in (OSM postcodes are sometimes wrong) "phone": t.get("phone", t.get("contact:phone", "")),
                    "email": t.get("email", t.get("contact:email", "")), "website": t.get("website", t.get("contact:website", "")),
                    "contact_name": "", "contact_title": "", "source": "OpenStreetMap",
                    "lon": round(lon, 6), "lat": round(lat, 6), "located_by": f"OpenStreetMap {el['type']} {el['id']}",
                    "result": "found (new)"})
    return pd.DataFrame(out)


# OSM finds left out of the public layer: places where people live or receive residential care
# (mapping them exposes residents), plus unions and fraternities. Reviewed 2026-10-16.
EXCLUDE_TYPES = {"Nursing Home", "Assisted Living", "Shelter"}
EXCLUDE_NAME = re.compile(r"\b(apartments?|manor|towers|residence|recovery residence|nursing|union local|"
                          r"alpha kappa|fraternity|sorority)\b", re.I)
EXCLUDE_NAMES = {"hannah house, inc.": "residential program", "help usa": "shelter / housing provider",
                 "fresh start": "residential program", "guild house west": "senior apartments",
                 "herbert arlene homes": "housing", "gilbert's shoes": "not a community organization"}
KEEP_NAME = re.compile(r"senior cent|community cent", re.I)   # e.g. a senior or community center in a housing complex stays


def screen(found):
    if found.empty:
        return found
    found = found.copy()
    for i, f in found[found["result"] == "found (new)"].iterrows():
        why = EXCLUDE_NAMES.get(f["name"].strip().lower())
        if not why and f["type"] in EXCLUDE_TYPES:
            why = f["type"].lower()
        if not why and EXCLUDE_NAME.search(f["name"]) and not KEEP_NAME.search(f["name"]):
            why = "residence, union or fraternity"
        if not why and not re.search(r"[A-Za-z]{3}", f["name"]):
            why = "no real name in OpenStreetMap"
        if why:
            found.at[i, "result"] = f"left out: {why}"
    return found


# Map categories, in priority order: an organization shows its first two matches (split symbol).
CATEGORIES = [
    ("Food", r"food|pantry|kitchen|philabundance|care closet|feeding"),
    ("Youth & education", r"youth|teen|child|kids|boys & girls|school|learning|education|college|cyber village|\bpal\b|athletic|idaay"),
    ("Seniors", r"senior|older adult|aging|adult day"),
    ("Health & social services", r"social service|human service|health|treatment|recovery|\bwic\b|family|women|congreso|catholic social|"
                                 r"united fund|resource center|advocate center|rescue mission|neighbors|guild|fathers? day|prison|second chance|benephilly|lift-"),
    ("Housing & civic", r"\bcdc\b|\bnac\b|civic|development|revitalization|habitat|alliance|energy coordinating|sanctuary|congress|"
                        r"advisory|neighborhood action|foundation|nonprofit|non profit"),
    ("Arts & culture", r"\barts?\b|mural|taller|cultur|historic"),
    ("Community centers & recreation", r"community cent|community building|recreation|rec center|ymca|\byac\b|community space|life center|"
                                       r"house, inc|community outreach|urban farm"),
    ("Faith-based", r"church|baptist|tabernacle|ministr|chapel|\ba\.?m\.?e\b|presbyterian|lutheran|methodist|catholic|iglesia|cristiano|"
                    r"holy|memorial temple|temple church|temple of|prayer|worship|moorish science|deliverance|redemption|redeem|"
                    r"faith|jerusalem|zion|morning star|pilgrim|bethel|commandment|sol de justicia|baabun nasr|father's house|st\. "),
]


def categories(name, kind):
    text = f"{name} | {kind}".lower()
    hits = [c for c, pat in CATEGORIES if re.search(pat, text)]
    return ";".join(hits[:2]) if hits else "Other"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("&", "and"))


def drop_duplicates_of_list(found, listed):
    """An OSM find within 60 m of a list entry, or with the same name, is the same organization."""
    if found.empty:
        return found
    lp = gpd.GeoDataFrame(listed, geometry=gpd.points_from_xy(listed["lon"], listed["lat"]), crs=4326).to_crs(2272)
    names = set(listed["name"].map(norm))
    keep = []
    for _, f in found.iterrows():
        p = gpd.GeoSeries([Point(f["lon"], f["lat"])], crs=4326).to_crs(2272).iloc[0]
        near = lp.distance(p).min() < 200 if len(lp) else False
        same = norm(f["name"]) in names or any(norm(f["name"])[:12] and norm(f["name"])[:12] in nm for nm in names)
        keep.append(not (same or (near and lp.distance(p).min() < 60)))
    found = found.copy()
    found.loc[[not k for k in keep], "result"] = "already on the list (OSM duplicate)"
    return found


def rcos(zips):
    feats, offset = [], 0
    while True:
        r = requests.get(f"{CITY_GIS}/Zoning_RCO/FeatureServer/0/query", timeout=300, params={
            "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson", "orderByFields": "objectid",
            "resultOffset": offset, "resultRecordCount": 1000})
        r.raise_for_status()
        b = r.json().get("features", [])
        feats += b
        offset += len(b)
        if len(b) < 1000:
            break
    g = gpd.GeoDataFrame.from_features(feats, crs=4326)
    g = g[g.geometry.notna()].copy()
    g["geometry"] = g.geometry.make_valid()
    touch = g[g.intersects(zips.union_all())].copy()
    # The service's field names are lowercase. Contacts' home addresses (primary/alternate_address)
    # are left out on purpose: many RCO contacts are volunteers listing their own house.
    touch.columns = [c.lower() if c != "geometry" else c for c in touch.columns]
    cols = {"organization_name": "name", "org_type": "org_type", "organization_address": "address",
            "meeting_location_address": "meeting_location", "websites": "website",
            "primary_name": "contact_name", "primary_phone": "phone", "primary_email": "email",
            "alternate_name": "alt_contact_name", "alternate_phone": "alt_phone", "alternate_email": "alt_email",
            "preffered_contact_method": "preferred_contact", "effective_date": "registered_since",
            "expirationyear": "registration_expires"}
    touch = touch[[c for c in cols if c in touch.columns] + ["geometry"]].rename(columns=cols)
    for c in ["address", "meeting_location"]:
        if c in touch:
            touch[c] = touch[c].fillna("").str.replace(r"\s+", " ", regex=True).str.strip()
    if "registered_since" in touch:   # epoch milliseconds -> year
        touch["registered_since"] = pd.to_datetime(pd.to_numeric(touch["registered_since"], errors="coerce"),
                                                   unit="ms", errors="coerce").dt.year.astype("Int64").astype(str).replace("<NA>", "")
    for c in ["phone", "alt_phone"]:
        if c in touch:
            d = touch[c].fillna("").str.replace(r"\D", "", regex=True)
            touch[c] = d.where(d.str.len() != 10, d.str[:3] + "-" + d.str[3:6] + "-" + d.str[6:])
    touch["geometry"] = touch.geometry.simplify(0.00002)
    print(f"RCOs: {len(g):,} citywide, {len(touch):,} touch a priority ZIP")
    return touch


def main():
    zips = priority_zips()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Placing the FIRM list ...")
    listed = load_list(zips, opa_points())
    print("Searching OpenStreetMap ...")
    found = screen(drop_duplicates_of_list(osm_finds(zips), listed[listed["result"] == "kept"]))
    review = pd.concat([listed, found], ignore_index=True)
    review.to_csv(OUT_DIR / "cbos_review.csv", index=False)

    review["categories"] = [categories(n, k) for n, k in zip(review["name"], review["type"])]
    pub = review[review["result"].isin(["kept", "found (new)"]) & review["lon"].notna()]
    gdf = gpd.GeoDataFrame(pub[PUBLISH_COLS], geometry=gpd.points_from_xy(pub["lon"], pub["lat"]), crs=4326)
    gdf.to_file(WEB_DATA / "cbos.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    rcos(zips).to_file(WEB_DATA / "rcos.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)

    print("\nFIRM list:", listed["result"].value_counts().to_dict(), "| located by:", listed["located_by"].value_counts().to_dict())
    print("OpenStreetMap:", found["result"].value_counts().to_dict() if len(found) else "nothing found")
    print(f"docs/data/cbos.geojson: {len(gdf)} organizations; review file: {OUT_DIR / 'cbos_review.csv'}")
    cats = pub["categories"].str.split(";")
    print("by category (an organization can have two):", cats.explode().value_counts().to_dict(),
          f"| with two categories: {int((cats.str.len() > 1).sum())}")


if __name__ == "__main__":
    main()
