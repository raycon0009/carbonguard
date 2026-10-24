"""
Fetch official project boundaries for selected projects from the open
carbon-project boundary database, reading only the rows we need over HTTP.

Data: Karnik, Kilbride, Goodbody, Ross, Ayrey (2024). A global database of
nature-based carbon offset project boundaries. Zenodo, record 11459391.
CC BY 4.0. https://zenodo.org/records/11459391

Run:  python ai/satellite/fetch_boundaries.py
Writes ai/data/external/boundaries/<ProjectID>.geojson (git-ignored).
"""
import json
import os
import sys
from pathlib import Path

ZENODO = "https://zenodo.org/api/records/11459391/files/{file}/content"
OUT = Path(__file__).resolve().parents[1] / "data" / "external" / "boundaries"
# Projects with OFFICIAL (registry-provided) boundaries, by GeoPackage file.
PROJECTS = {
    "africa.gpkg": ["VCS902", "VCS612"],  # Kariba (Zimbabwe), Kasigau Corridor II (Kenya)
    "asia.gpkg": ["VCS1748"],  # Southern Cardamom (Cambodia)
    "south_america.gpkg": ["VCS944"],  # Alto Mayo (Peru)
}

# Zenodo rate-limits bursts of range requests; retry and use large chunks.
os.environ.update(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MAX_RETRY="8",
    GDAL_HTTP_RETRY_DELAY="3",
    CPL_VSIL_CURL_CHUNK_SIZE="1048576",
    VSI_CACHE="TRUE",
    VSI_CACHE_SIZE="200000000",
)


def fetch(gpkg, wanted):
    import pyogrio
    import shapely

    url = "/vsicurl/" + ZENODO.format(file=gpkg)
    ids = pyogrio.read_dataframe(url, columns=["ProjectID"], read_geometry=False)
    for pid in wanted:
        out = OUT / f"{pid}.geojson"
        if out.exists():
            print(f"{pid}: cached")
            continue
        rows = ids.index[ids["ProjectID"] == pid].tolist()
        if not rows:
            print(f"{pid}: not in {gpkg}")
            continue
        row = pyogrio.read_dataframe(url, read_geometry=False, skip_features=rows[0], max_features=1)
        rec = row.iloc[0]
        geom = shapely.from_wkt(rec["Project Area"])
        feature = {
            "type": "Feature",
            "geometry": json.loads(shapely.to_geojson(geom)),
            "properties": {
                "ProjectID": pid,
                "name": rec["Project Name"],
                "country": rec["Country"],
                "processing_approach": rec["Processing Approach"],
                "crediting_start": rec["Project Start Date"],
                "source": "Karnik et al. (2024), Zenodo 11459391, CC BY 4.0",
            },
        }
        out.write_text(json.dumps(feature))
        print(f"{pid}: {rec['Project Name']} ({rec['Processing Approach']}), "
              f"{geom.geom_type}, bounds {tuple(round(b, 3) for b in geom.bounds)}")


def main():
    import warnings
    warnings.filterwarnings("ignore", message=".*non conformant file extension.*")
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for gpkg, wanted in PROJECTS.items():
        wanted = [p for p in wanted if not only or p in only]
        if wanted:
            fetch(gpkg, wanted)


if __name__ == "__main__":
    main()
