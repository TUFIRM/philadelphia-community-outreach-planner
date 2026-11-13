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
    data/processed/community_orgs/cbos_edits.xlsx  every list entry and OSM find,
        with what happened to it (kept, outside the ZIPs, how it was located).
        Edit it directly in Excel (see "the editable review workbook" below):
        decision keep/remove, checked date, corrected name/type/address/contacts/lat/lon.
        Your edits are read back and kept on every run. OpenStreetMap finds not updated
        in 2+ years are shaded orange until you fill in checked or decision.

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
OVERPASS_URLS = [OVERPASS, "https://overpass.private.coffee/api/interpreter"]   # same backup the app uses
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = {"User-Agent": "Temple FIRM community outreach planner (firm@temple.edu)"}
# type = the standard category (one of CATEGORIES, or Other); type_detail = what the FIRM list or OpenStreetMap called it
PUBLISH_COLS = ["name", "type", "type_detail", "categories", "address", "zip", "phone", "email", "website",
                "contact_name", "contact_title", "source"]
STALE_YEARS = 2     # OpenStreetMap finds not touched for this long are flagged (orange) in cbos_edits.xlsx
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
    q = "[out:json][timeout:120];(" + "".join(f"{f}({s},{w},{n},{e});" for f in OSM_FILTERS) + ");out center tags meta;"
    elements, last = None, None
    for attempt in range(6):                  # main server and a backup, a few rounds (Overpass is often busy)
        url = OVERPASS_URLS[attempt % len(OVERPASS_URLS)]
        try:
            r = requests.post(url, data={"data": q}, headers=UA, timeout=180)
            r.raise_for_status()
            elements = r.json().get("elements", [])
            break
        except (requests.RequestException, ValueError) as err:
            last = err
            wait = 30 * (attempt // len(OVERPASS_URLS) + 1)
            print(f"  Overpass ({url}) failed: {err}; trying again in {wait}s")
            time.sleep(wait)
    if elements is None:
        raise RuntimeError(f"OpenStreetMap (Overpass) did not answer: {last}")
    out = []
    for el in elements:
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
                    # last time anyone touched it in OSM (or its check_date): shown in the popup so stale entries stand out
                    "osm_updated": (t.get("check_date") or el.get("timestamp", ""))[:10],
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


# Map categories, in priority order: the script guesses up to two (split symbol); a person can set
# any number in the type column of cbos_edits.xlsx.
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


STANDARD_TYPES = [c for c, _ in CATEGORIES] + ["Other"]


def categories(name, kind):
    """Up to two standard categories guessed from the name and the source's own description.
    A person can set any number in the type column of cbos_edits.xlsx (see parse_types)."""
    text = f"{name} | {kind}".lower()
    hits = [c for c, pat in CATEGORIES if re.search(pat, text)]
    return ";".join(hits[:2]) if hits else "Other"


def parse_types(text):
    """'Food; Faith-based' (or commas) -> (['Food', 'Faith-based'], [parts that are not standard types])."""
    by_lower = {t.lower(): t for t in STANDARD_TYPES}
    good, bad = [], []
    for part in re.split(r"[;,]", str(text)):
        part = part.strip()
        if not part:
            continue
        t = by_lower.get(part.lower())
        (good if t else bad).append(t or part)
    return list(dict.fromkeys(good)), bad


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


# ---------------------------------------------------------------- the editable review workbook
# Two files, two jobs:
#   cbos_to_check.xlsx  WHAT TO CHECK (read-only, rewritten every run): OpenStreetMap entries not
#                                updated in 2+ years, and FIRM-list addresses that could not be placed
#   cbos_edits.xlsx     WHERE YOU EDIT: every organization; your edits are kept on every run
# data/processed/community_orgs/cbos_edits.xlsx lists every organization. Edit it directly in Excel:
#   decision  remove = leave it off the map; keep = put it on the map even if a filter left it out
#   checked   the date you confirmed it still operates (clears the orange flag)
#   notes     anything
#   name, type, type_detail, address, zip, phone, email, website, contact_name, contact_title, lat, lon
#             type it in and the map uses your value. type = one or more standard types separated
#             by ; (e.g. "Food; Faith-based"); the map pin is split into one color per type
# Each run reads the workbook first and carries your edits forward by the row's id, so untouched cells
# still pick up new City / OpenStreetMap data. A hidden sheet (_generated) holds what the script itself
# wrote last time; a cell that differs from it is your edit. Edited cells turn blue as you type
# (conditional formatting against _generated), and decision / checked / notes are blue when filled in.
REVIEW_XLSX = OUT_DIR / "cbos_edits.xlsx"            # where you edit (and the full reference list)
# Read-only list of what to check, rewritten on every run. Make the changes in cbos_edits.xlsx.
SUGGEST_XLSX = OUT_DIR / "cbos_to_check.xlsx"
EDITABLE = ["name", "type", "type_detail", "address", "zip", "phone", "email", "website",
            "contact_name", "contact_title", "lat", "lon"]
HAND = ["decision", "checked", "notes"]                 # only ever filled in by a person
REVIEW_COLS = ["needs_check", "decision", "checked", "notes", "name", "type", "type_detail",
               "address", "zip", "phone", "email", "website", "contact_name", "contact_title", "result",
               "source", "osm_updated", "located_by", "lat", "lon", "id"]


def cell(v, field=""):
    """A value as text, for comparing what is in the workbook with what the script generated."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    if field in ("lat", "lon"):
        try:
            return f"{float(v):.6f}"
        except ValueError:
            return str(v).strip()
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    return s[:-2] if field == "zip" and s.endswith(".0") else s


def read_edits():
    """id -> {field: value} for every cell a person changed in the workbook, plus decision / checked / notes."""
    if not REVIEW_XLSX.exists():
        return {}
    try:
        book = pd.read_excel(REVIEW_XLSX, sheet_name=None, dtype=object)
    except PermissionError:
        raise SystemExit(f"{REVIEW_XLSX.name} is locked - close it in Excel and run script 09 again "
                         "(your edits in it are read on every run)")
    seen, gen = book.get("review"), book.get("_generated")
    if seen is None or "id" not in seen:
        return {}
    gen = {cell(r["id"]): r for _, r in gen.iterrows()} if gen is not None and "id" in gen else {}
    edits = {}
    for _, r in seen.iterrows():
        rid = cell(r["id"])
        if not rid:
            continue
        g, e = gen.get(rid), {}
        for f in HAND:
            if f in r and cell(r[f]):
                e[f] = cell(r[f])
        for f in EDITABLE:
            if f in r and g is not None and f in g and cell(r[f], f) != cell(g[f], f):
                e[f] = cell(r[f], f)
        if e:
            edits[rid] = e
    return edits


def apply_edits(review, edits):
    """Put a person's edits on top of the freshly generated rows. Returns the rows and the set of edited cells."""
    edited, gone = set(), []
    index = {rid: i for i, rid in review["id"].items()}
    for rid, e in edits.items():
        i = index.get(rid)
        if i is None:
            gone.append(rid)
            continue
        for f, v in e.items():
            if f == "type":
                good, bad = parse_types(v)
                if bad:
                    print(f"  {review.at[i, 'name']}: {bad} not standard types {STANDARD_TYPES} - ignored")
                if not good:
                    continue
                review.at[i, "categories"] = ";".join(good)
                v = "; ".join(good)
            if f in ("lat", "lon"):
                try:
                    v = float(v)
                except ValueError:
                    print(f"  {review.at[i, 'name']}: {f} {v!r} is not a number - ignored")
                    continue
            review.at[i, f] = v
            if f in EDITABLE:
                edited.add((i, f))
        if (i, "type") not in edited and ((i, "name") in edited or (i, "type_detail") in edited):
            review.at[i, "categories"] = categories(review.at[i, "name"], review.at[i, "type_detail"])
            review.at[i, "type"] = review.at[i, "categories"].replace(";", "; ")
        d = str(review.at[i, "decision"]).strip().lower()
        if d == "remove":
            review.at[i, "result"] = "left out: removed in the review"
        elif d == "keep" and not review.at[i, "result"] in ("kept", "found (new)"):
            review.at[i, "result"] = "kept (review)"
        elif d and d not in ("keep", "remove"):
            print(f"  {review.at[i, 'name']}: decision {d!r} should be keep or remove - ignored")
    for rid in gone:
        print(f"  edited row no longer found (removed from OpenStreetMap or the FIRM list): {rid} {edits[rid]}")
    return review, edited


def needs_check(r):
    """Flag OpenStreetMap finds nobody has updated in STALE_YEARS, until someone fills in checked or decision."""
    if r["source"] != "OpenStreetMap" or r["result"] != "found (new)" or r["checked"] or r["decision"]:
        return ""
    upd = str(r["osm_updated"] or "")
    if not re.match(r"\d{4}-\d{2}-\d{2}", upd):
        return "check: no update date in OpenStreetMap"
    age = (pd.Timestamp.today() - pd.Timestamp(upd)).days / 365.25
    return f"check: last updated in OpenStreetMap {upd[:7]} ({age:.1f} years ago)" if age >= STALE_YEARS else ""


def write_review(review, generated, edited):
    from openpyxl.formatting.rule import FormulaRule
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    review = review.reindex(columns=REVIEW_COLS).reset_index(drop=True)
    try:
        with pd.ExcelWriter(REVIEW_XLSX, engine="openpyxl") as xw:
            review.to_excel(xw, index=False, sheet_name="review")
            generated.reindex(columns=["id"] + EDITABLE).to_excel(xw, index=False, sheet_name="_generated")
            ws = xw.sheets["review"]
            xw.sheets["_generated"].sheet_state = "hidden"
            orange = PatternFill("solid", fgColor="FFC58F")
            blue = PatternFill("solid", start_color="BDD7EE", end_color="BDD7EE")   # conditional formats use bgColor
            for n, flag in enumerate(review["needs_check"], start=2):
                if flag:
                    for c in ws[n]:
                        c.fill = orange
            for c in ws[1]:
                c.font = Font(bold=True)
            last = len(review) + 1
            # blue = a manual change, live while you type: a cell that differs from what the script wrote
            # (looked up by id in the hidden _generated sheet, so sorting the sheet is fine)
            letter = lambda col: get_column_letter(REVIEW_COLS.index(col) + 1)
            idc = letter("id")
            for k, f in enumerate(EDITABLE):
                L, G = letter(f), get_column_letter(k + 2)
                rule = FormulaRule(formula=[f'IFERROR(${idc}2<>"",FALSE)*IFERROR({L}2&""<>INDEX(_generated!${G}:${G},'
                                            f'MATCH(${idc}2,_generated!$A:$A,0))&"",FALSE)'], fill=blue)
                ws.conditional_formatting.add(f"{L}2:{L}{last}", rule)
            for f in HAND:
                L = letter(f)
                ws.conditional_formatting.add(f"{L}2:{L}{last}", FormulaRule(formula=[f'LEN({L}2)>0'], fill=blue))
            dv = DataValidation(type="list", formula1='"keep,remove"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(f"{letter('decision')}2:{letter('decision')}{last}")
            # type: pick one from the list, or type several separated by ; (so no error on other values)
            dv = DataValidation(type="list", formula1='"' + ",".join(STANDARD_TYPES) + '"', allow_blank=True,
                                showErrorMessage=False, showInputMessage=True, promptTitle="type",
                                prompt="Pick one, or type several separated by ;  e.g. Food; Faith-based")
            ws.add_data_validation(dv)
            dv.add(f"{letter('type')}2:{letter('type')}{last}")
            ws.freeze_panes = "F2"
            ws.auto_filter.ref = ws.dimensions
            for j, col in enumerate(REVIEW_COLS, start=1):
                width = max([len(col)] + [len(cell(v)) for v in review[col]])
                ws.column_dimensions[get_column_letter(j)].width = min(max(width, 8), 45) + 2
    except PermissionError:
        raise SystemExit(f"{REVIEW_XLSX.name} is open in Excel - close it and run script 09 again")
    write_suggestions(review)


def write_suggestions(review):
    """cbos_to_check.xlsx: only the rows worth checking, with links, locked so nobody edits it by mistake."""
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    s = review[review["needs_check"] != ""].copy()
    nf = review[(review["source"] == "FIRM list") & review["lon"].isna()].copy()
    nf["needs_check"] = "check: address could not be placed on the map - fix address or lat/lon"
    s = pd.concat([s, nf])
    osm = s["id"].str.extract(r"OpenStreetMap (node|way|relation) (\d+)")
    s["openstreetmap_link"] = ("https://www.openstreetmap.org/" + osm[0] + "/" + osm[1]).fillna("")
    s["google_search"] = "https://www.google.com/search?q=" + (s["name"] + " " + s["address"].fillna("") +
                                                              " Philadelphia").str.replace(" ", "+", regex=False)
    s = s.sort_values(["osm_updated", "name"])
    cols = ["needs_check", "name", "type", "type_detail", "address", "phone", "website", "osm_updated",
            "openstreetmap_link", "google_search", "id"]
    s = s.reindex(columns=cols)
    note = (f"SUGGESTIONS ONLY - this file is rewritten on every run. To act on a row, open {REVIEW_XLSX.name}, "
            "find the same id, and fill in decision (keep / remove) and checked (today's date).")
    try:
        with pd.ExcelWriter(SUGGEST_XLSX, engine="openpyxl") as xw:
            s.to_excel(xw, index=False, sheet_name="to check", startrow=2)
            ws = xw.sheets["to check"]
            ws["A1"] = note
            ws["A1"].font = Font(bold=True, color="9A3412")
            ws["A1"].alignment = Alignment(wrap_text=False)
            ws["A2"] = f"{len(s)} to check, oldest first. Made {pd.Timestamp.today():%Y-%m-%d}."
            orange = PatternFill("solid", fgColor="FFC58F")
            for row in ws.iter_rows(min_row=4, max_row=len(s) + 3):
                for c in row:
                    c.fill = orange
            for c in ws[3]:
                c.font = Font(bold=True)
            for n, url in enumerate(s["openstreetmap_link"], start=4):
                for col in ("openstreetmap_link", "google_search"):
                    c = ws.cell(row=n, column=cols.index(col) + 1)
                    if c.value:
                        c.hyperlink, c.style = c.value, "Hyperlink"
                        c.fill = orange
            ws.freeze_panes = "C4"
            for j, col in enumerate(cols, start=1):
                width = max([len(col)] + [len(cell(v)) for v in s[col]])
                ws.column_dimensions[get_column_letter(j)].width = min(max(width, 8), 40) + 2
            ws.protection.sheet = True                  # read-only: no password, it only prevents accidental edits
            ws.protection.autoFilter = False
    except PermissionError:
        print(f"  WARNING: {SUGGEST_XLSX.name} is open in Excel and was not updated")


def main():
    zips = priority_zips()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Placing the FIRM list ...")
    listed = load_list(zips, opa_points())
    print("Searching OpenStreetMap ...")
    found = screen(drop_duplicates_of_list(osm_finds(zips), listed[listed["result"] == "kept"]))
    edits = read_edits()                           # read your edits before anything is rewritten
    review = pd.concat([listed, found], ignore_index=True)
    review["id"] = review["located_by"].where(review["source"] == "OpenStreetMap", "FIRM list: " + review["name"])
    for c in ["decision", "checked", "notes"]:
        review[c] = ""
    review = review.fillna({c: "" for c in ["name", "type", "osm_updated", "source", "result"]})
    review["type_detail"] = review["type"]           # what the FIRM list / OpenStreetMap called it
    review["categories"] = [categories(n, k) for n, k in zip(review["name"], review["type_detail"])]
    review["type"] = review["categories"].str.replace(";", "; ", regex=False)
    generated = review.copy()
    review, edited = apply_edits(review, edits)
    review["needs_check"] = review.apply(needs_check, axis=1)
    write_review(review, generated, edited)
    print(f"Review edits: {len(edits)} rows carried forward, {len(edited)} edited cells")
    pub = review[review["result"].isin(["kept", "found (new)", "kept (review)"]) & review["lon"].notna()]
    gdf = gpd.GeoDataFrame(pub.reindex(columns=PUBLISH_COLS).fillna(""), geometry=gpd.points_from_xy(pub["lon"], pub["lat"]), crs=4326)
    gdf.to_file(WEB_DATA / "cbos.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)
    rcos(zips).to_file(WEB_DATA / "rcos.geojson", driver="GeoJSON", COORDINATE_PRECISION=6)

    print("\nFIRM list:", listed["result"].value_counts().to_dict(), "| located by:", listed["located_by"].value_counts().to_dict())
    print("OpenStreetMap:", found["result"].value_counts().to_dict() if len(found) else "nothing found")
    print(f"docs/data/cbos.geojson: {len(gdf)} organizations; edits: {REVIEW_XLSX} "
          f"| to check: {SUGGEST_XLSX} ({int((review['needs_check'] != '').sum())} rows)")
    cats = pub["categories"].str.split(";")
    print("by category (an organization can have two):", cats.explode().value_counts().to_dict(),
          f"| with two categories: {int((cats.str.len() > 1).sum())}")


if __name__ == "__main__":
    main()
