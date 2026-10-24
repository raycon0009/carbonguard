"""
Measure how much deforestation a REDD+ project actually avoided, from real
satellite data, and compare it with the credits it was issued.

Method (a simplified, first-order version of the published approach):
  1. Boundary: the project's official polygon (fetch_boundaries.py).
  2. Control: a ring 2-20 km around the project (the 2 km gap limits spill-over).
  3. Satellite: Hansen Global Forest Change v1.12 'lossyear' (30 m, 2001-2024)
     and 'datamask' (land vs water). Loss is measured per hectare of LAND.
  4. Two standard counterfactuals for "what would have happened without it":
       - before/after (difference-in-differences): the project's own pre-project
         loss rate, adjusted by the change seen in the ring over the same years;
       - surroundings: the project would have lost forest like its ring.
     Avoided loss = counterfactual rate - actual rate. We keep whichever method
     credits the project MORE, so the reported gap is the most favourable one.
  5. Carbon: avoided hectares x a forest carbon density (IPCC 2019 refined
     defaults via Rozendaal et al. 2022). We use high-end densities, which
     can only make the project look BETTER - a conservative test.
  6. Gap = 1 - avoided tCO2 / tCO2 credited. That is the same quantity as the
     model's satellite feature: "satellite shows X% less avoided loss than claimed".

Also reported: the break-even density - how carbon-dense the forest would have
to be for the credits to be justified by the observed avoided loss.

Data: Hansen et al. (2013) Science 342:850-853, GFC-2024-v1.12, CC BY 4.0.
Run:  python ai/satellite/measure.py            (needs boundaries + VROD workbook)
"""
import json
import math
import os
from pathlib import Path

import numpy as np

AI = Path(__file__).resolve().parents[1]
EXTERNAL = AI / "data" / "external"
BOUNDARIES = EXTERNAL / "boundaries"
CACHE = EXTERNAL / "satellite"
OUT = AI / "real_world" / "satellite.json"

HANSEN = "https://storage.googleapis.com/earthenginepartners-hansen/GFC-2024-v1.12/Hansen_GFC-2024-v1.12_{layer}_{tile}.tif"
RES = 0.00025  # degrees per pixel (~30 m)
LAST_YEAR = 2024  # lossyear 1..24 = 2001..2024
RING_KM = (2, 20)
PRE_YEARS = 10
# Hansen tracks trees taller than 5 m. In shrubland it sees almost nothing, so a
# measurement only counts if the record shows real loss before the project began.
MIN_PRE_LOSS_HA = 1000

# Above-ground biomass, t dry matter / ha (IPCC 2019 refined defaults, Rozendaal et al. 2022).
AGB = {"dry": 127.5, "moist": 187.3, "montane": 195.0, "rain": 307.1}
ROOT_SHARE = 0.25  # below-ground biomass added on top
CARBON_FRACTION = 0.47
CO2_PER_C = 44 / 12
ZONES = {"VCS902": "dry", "VCS612": "dry", "VCS1748": "rain", "VCS944": "montane"}


def tco2_per_ha(zone):
    return AGB[zone] * (1 + ROOT_SHARE) * CARBON_FRACTION * CO2_PER_C


# ----------------------------------------------------------------- pure maths

def loss_rate(loss_by_year, land_ha, years):
    """Average share of land lost per year over `years` (iterable of calendar years)."""
    years = [y for y in years if 2001 <= y <= LAST_YEAR]
    if not years or land_ha <= 0:
        return float("nan")
    return sum(loss_by_year.get(y, 0.0) for y in years) / land_ha / len(years)


def estimate_gap(project_loss, project_land_ha, ring_loss, ring_land_ha, start, end, claimed_tco2, density):
    """
    Difference-in-differences estimate of avoided deforestation vs. credits.
    *_loss: {year: hectares lost}. Returns a dict of the intermediate numbers.
    """
    end = min(end, LAST_YEAR)
    pre = range(max(2001, start - PRE_YEARS), start)
    during = range(start, end + 1)
    p_pre, p_dur = loss_rate(project_loss, project_land_ha, pre), loss_rate(project_loss, project_land_ha, during)
    r_pre, r_dur = loss_rate(ring_loss, ring_land_ha, pre), loss_rate(ring_loss, ring_land_ha, during)
    pre_loss_ha = sum(project_loss.get(y, 0.0) for y in pre if 2001 <= y <= LAST_YEAR)
    measurable = pre_loss_ha >= MIN_PRE_LOSS_HA
    years = len(during)

    def judge(expected):
        avoided_ha = max(0.0, expected - p_dur) * project_land_ha * years
        gap = 1.0 if claimed_tco2 <= 0 else min(1.0, max(0.0, 1 - avoided_ha * density / claimed_tco2))
        return avoided_ha, gap

    expected_did = max(0.0, p_pre + (r_dur - r_pre))
    expected_ring = max(0.0, r_dur)
    did_ha, did_gap = judge(expected_did)
    ring_ha, ring_gap = judge(expected_ring)
    # Most favourable to the project.
    method, expected, avoided_ha, gap = (("before_after", expected_did, did_ha, did_gap) if did_gap <= ring_gap
                                         else ("surroundings", expected_ring, ring_ha, ring_gap))
    observed_tco2 = avoided_ha * density
    return {
        "measurable": measurable,
        "not_measurable_reason": None if measurable else (
            f"only {pre_loss_ha:,.0f} ha of tree-cover loss detected in the project before it started "
            f"(minimum {MIN_PRE_LOSS_HA:,}); the satellite product cannot see this landscape"),
        "project_loss_ha_pre": pre_loss_ha,
        "pre_period": [pre.start, pre.stop - 1],
        "crediting_period": [start, end],
        "project_loss_rate_pre": p_pre,
        "project_loss_rate_during": p_dur,
        "ring_loss_rate_pre": r_pre,
        "ring_loss_rate_during": r_dur,
        "expected_project_loss_rate": expected,
        "method_used": method,
        "gap_before_after": did_gap,
        "gap_surroundings": ring_gap,
        "avoided_ha": avoided_ha,
        "observed_avoided_tco2": observed_tco2,
        "claimed_tco2": claimed_tco2,
        "gap": gap,
        "break_even_tco2_per_ha": (claimed_tco2 / avoided_ha) if avoided_ha > 0 else math.inf,
        # Upper bound: even if the project had stopped ALL the loss expected without it,
        # this is the most of its credits the satellite record could support.
        "max_supported_share": min(1.0, max(expected_did, expected_ring) * project_land_ha * years * density / claimed_tco2)
        if claimed_tco2 > 0 else 0.0,
    }


def tile_names(bounds):
    """Hansen 10x10 degree tiles (named by top-left corner) covering lon/lat bounds."""
    minx, miny, maxx, maxy = bounds
    names = []
    for top in range(int(math.ceil(maxy / 10) * 10), int(math.floor(miny / 10) * 10), -10):
        for left in range(int(math.floor(minx / 10) * 10), int(math.ceil(maxx / 10) * 10), 10):
            lat = f"{abs(top):02d}{'N' if top >= 0 else 'S'}"
            lon = f"{abs(left):03d}{'E' if left >= 0 else 'W'}"
            names.append((f"{lat}_{lon}", top, left))
    return names


# ----------------------------------------------------------------- satellite I/O

def read_layer(layer, bounds, cache_key):
    """Mosaic one Hansen layer over bounds (lon/lat), reading only the needed rows. Cached."""
    import rasterio
    from rasterio.windows import Window

    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{cache_key}_{layer}.npz"
    minx, miny, maxx, maxy = bounds
    left, top = math.floor(minx / RES) * RES, math.ceil(maxy / RES) * RES
    width, height = int(round((math.ceil(maxx / RES) * RES - left) / RES)), int(round((top - math.floor(miny / RES) * RES) / RES))
    if cached.exists():
        z = np.load(cached)
        return z["data"], (float(z["left"]), float(z["top"]))
    out = np.zeros((height, width), dtype=np.uint8)
    env = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MAX_RETRY="8", GDAL_HTTP_RETRY_DELAY="3",
               CPL_VSIL_CURL_CHUNK_SIZE="4194304")
    with rasterio.Env(**env):
        for name, ttop, tleft in tile_names(bounds):
            # Overlap of the request with this tile, in global pixel coordinates.
            c0, c1 = max(left, tleft), min(left + width * RES, tleft + 10)
            r0, r1 = min(top, ttop), max(top - height * RES, ttop - 10)
            if c1 <= c0 or r0 <= r1:
                continue
            win = Window(int(round((c0 - tleft) / RES)), int(round((ttop - r0) / RES)),
                         int(round((c1 - c0) / RES)), int(round((r0 - r1) / RES)))
            with rasterio.open("/vsicurl/" + HANSEN.format(layer=layer, tile=name)) as src:
                block = src.read(1, window=win)
            oc, orow = int(round((c0 - left) / RES)), int(round((top - r0) / RES))
            out[orow:orow + block.shape[0], oc:oc + block.shape[1]] = block
            print(f"    {layer} {name}: {block.shape[1]}x{block.shape[0]} px", flush=True)
    np.savez_compressed(cached, data=out, left=left, top=top)
    return out, (left, top)


SIMPLIFY_DEG = 0.0005  # ~50 m, under two 30 m pixels


def clean(geom):
    """Repair and simplify a boundary. Some official boundaries are traced from
    pixels (thousands of parts, hundreds of thousands of vertices); ~50 m
    simplification keeps the measurement identical at 30 m resolution."""
    import shapely

    # Plain Douglas-Peucker then buffer(0): seconds, where make_valid on the raw shape takes many minutes.
    return shapely.simplify(geom, SIMPLIFY_DEG, preserve_topology=False).buffer(0)


def regions(geom):
    """Project polygon and a 2-20 km control ring, both in lon/lat."""
    import geopandas as gpd

    g = gpd.GeoSeries([clean(geom)], crs="EPSG:4326")
    utm = g.estimate_utm_crs()
    gu = g.to_crs(utm)
    ring = gu.buffer(RING_KM[1] * 1000).difference(gu.buffer(RING_KM[0] * 1000))
    return g.iloc[0], ring.to_crs("EPSG:4326").iloc[0]


def measure_project(pid, claimed_tco2, start, end):
    import shapely
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin

    feature = json.loads((BOUNDARIES / f"{pid}.geojson").read_text())
    project, ring = regions(shapely.geometry.shape(feature["geometry"]))
    bounds = ring.union(project).bounds
    print(f"{pid} {feature['properties']['name']}: bounds {tuple(round(b, 2) for b in bounds)}", flush=True)
    loss, (left, top) = read_layer("lossyear", bounds, pid)
    land, _ = read_layer("datamask", bounds, pid)
    transform = from_origin(left, top, RES, RES)

    # Pixel area shrinks with latitude.
    lat = top - (np.arange(loss.shape[0]) + 0.5) * RES
    px_ha = (RES * 111_320 * np.cos(np.radians(lat))) * (RES * 110_574) / 10_000
    area = np.broadcast_to(px_ha[:, None], loss.shape)

    out = {}
    for label, geom in (("project", project), ("ring", ring)):
        inside = ~geometry_mask([geom], out_shape=loss.shape, transform=transform) & (land == 1)
        by_year = np.bincount(loss[inside], weights=area[inside], minlength=LAST_YEAR - 2000 + 1)
        out[label] = {
            "land_ha": float(area[inside].sum()),
            "loss_ha_by_year": {2000 + y: float(by_year[y]) for y in range(1, LAST_YEAR - 2000 + 1)},
        }
    zone = ZONES[pid]
    density = tco2_per_ha(zone)
    est = estimate_gap(out["project"]["loss_ha_by_year"], out["project"]["land_ha"],
                       out["ring"]["loss_ha_by_year"], out["ring"]["land_ha"],
                       start, end, claimed_tco2, density)
    return {
        "project_id": pid,
        "name": feature["properties"]["name"],
        "boundary_source": feature["properties"]["source"],
        "boundary_type": feature["properties"]["processing_approach"],
        "forest_zone": zone,
        "tco2_per_ha_assumed": round(density, 1),
        # JSON has no infinity: an unknown break-even density (nothing avoided) is null.
        **{k: ((round(v, 6) if math.isfinite(v) else None) if isinstance(v, float) else v) for k, v in est.items()},
        "project_land_ha": round(out["project"]["land_ha"]),
        "ring_land_ha": round(out["ring"]["land_ha"]),
        "project_loss_ha_by_year": {k: round(v, 1) for k, v in out["project"]["loss_ha_by_year"].items()},
        "ring_loss_ha_by_year": {k: round(v, 1) for k, v in out["ring"]["loss_ha_by_year"].items()},
    }


def claims_from_vrod(pids):
    """Gross credits claimed (issued + buffer share) per project for vintages <= LAST_YEAR."""
    import pandas as pd
    import validate_real_world as vr

    vrod, vintage_cols = vr.load_vrod(vr.DEFAULT_XLSX)
    vrod = vrod[vrod["Project ID"].isin(pids)].set_index("Project ID")
    claims = {}
    def num(v):
        return float(np.nan_to_num(pd.to_numeric(v, errors="coerce")))

    for pid, r in vrod.iterrows():
        by_vintage = {int(y): num(r[y]) for y in vintage_cols}
        credited = {y: v for y, v in by_vintage.items() if v > 0 and y <= LAST_YEAR}
        issued_total = num(r["Total Credits \nIssued"])
        buffer = num(r["Total Buffer \nPool Deposits"])
        issued = sum(credited.values())
        gross = issued + buffer * (issued / issued_total if issued_total else 0)
        claims[pid] = {"claimed_tco2": gross, "start": min(credited), "end": max(credited),
                       "issued_in_window": issued, "buffer_share": gross - issued}
    return claims


def main():
    import sys
    sys.path.insert(0, str(AI))
    pids = sys.argv[1:] or sorted(p.stem for p in BOUNDARIES.glob("*.geojson"))
    claims = claims_from_vrod(pids)
    # Keep earlier results for projects not re-measured in this run.
    previous = json.loads(OUT.read_text())["projects"] if OUT.exists() else []
    results = [p for p in previous if p["project_id"] not in pids]
    for pid in pids:
        c = claims[pid]
        r = measure_project(pid, c["claimed_tco2"], c["start"], c["end"])
        r.update({k: round(v) if isinstance(v, float) else v for k, v in c.items() if k != "claimed_tco2"})
        results.append(r)
        print(f"  -> gap {r['gap']:.0%} via {r['method_used']} (before/after {r['gap_before_after']:.0%}, "
              f"surroundings {r['gap_surroundings']:.0%}; at most {r['max_supported_share']:.1%} supportable)  "
              f"avoided {r['avoided_ha']:,.0f} ha  claimed {c['claimed_tco2']:,.0f} tCO2  "
              f"break-even {r['break_even_tco2_per_ha']} tCO2/ha (assumed {r['tco2_per_ha_assumed']})", flush=True)
    OUT.write_text(json.dumps({
        "method": __doc__.split("Method")[1].split("Data:")[0].strip(),
        "sources": {
            "satellite": "Hansen et al. (2013) Science 342:850-853; Global Forest Change GFC-2024-v1.12 (lossyear, datamask), CC BY 4.0",
            "boundaries": "Karnik, Kilbride, Goodbody, Ross, Ayrey (2024). A global database of nature-based carbon offset project boundaries. Zenodo 11459391, CC BY 4.0",
            "carbon_density": "IPCC 2019 Refinement defaults, as compiled by Rozendaal et al. (2022) Environ. Res. Lett.",
            "credits": "Berkeley Voluntary Registry Offsets Database v2026-08 (issued + buffer share, vintages <= 2024)",
        },
        "projects": results,
    }, indent=1))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
