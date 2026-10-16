"""
07_publish_reference_layers.py

Copies the hand-placed map layers from data/raw/reference/ into docs/data/ so
the web app picks up any edits. These layers have no download script; their
editable copies live here (not in git):

    data/raw/reference/city/      City of Philadelphia layers (City_Limits,
                                  Council_Districts_2024, Police_Stations,
                                  NeighborhoodAdvisoryCommittees, NAC_Offices)
    data/raw/reference/temple/    Temple University layers (TU_buildings,
                                  TU_police_boundary, TU_Police_Stations)
    data/raw/reference/project/   Project layers (Polygons_of_interest,
                                  Schools_of_Interest) and the source KML

Each file must be valid GeoJSON with features in WGS84 (lon/lat), and keep the
same file name: the app loads docs/data/<same name>. The KML is not published.
See DATA_SOURCES.md for where each layer came from.

Run from the repo root:
    python scripts/07_publish_reference_layers.py
"""

import json

from common import RAW, WEB_DATA, publish

REFERENCE = RAW / "reference"


def main():
    files = sorted(REFERENCE.glob("*/*.geojson"))
    if not files:
        raise FileNotFoundError(f"No GeoJSON files found under {REFERENCE}")
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        feats = data.get("features") if data.get("type") == "FeatureCollection" else None
        if not feats:
            print(f"  SKIPPED {path.relative_to(REFERENCE)}: not a FeatureCollection with features")
            continue
        print(f"{path.relative_to(REFERENCE)}: {len(feats):,} features")
        publish(path)


if __name__ == "__main__":
    main()
