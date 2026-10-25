"""
Build ai/data/real_projects.csv: every real project with issued credits in the
Berkeley Voluntary Registry Offsets Database, in the model's input schema.

- Satellite: projects measured by ai/satellite/measure.py get their measured
  gap (only where the satellite record can actually measure the landscape).
- Holdout: projects used to judge the model (the watch list, satellite-measured
  projects, and the California projects graded in grade_california.py) are
  marked holdout=True and never used for training, so their scores are honest
  out-of-sample tests.

The CSV is committed (CC BY 4.0, with attribution) so anyone can retrain
without the 16 MB workbook.

Data: Quartson, Haya, Bernard, Abayo, Rong, So, Elias (2026). Voluntary Registry
Offsets Database v2026-08, Berkeley Carbon Trading Project, UC Berkeley. CC BY 4.0.

Run:  python ai/build_real_dataset.py
"""
import json
from pathlib import Path

import pandas as pd

import validate_real_world as vr

HERE = Path(__file__).parent
REAL = HERE / "data" / "real_projects.csv"
REAL_META = HERE / "data" / "real_projects_meta.json"
SATELLITE = HERE / "real_world" / "satellite.json"


def holdout_ids():
    ids = set(pd.read_csv(vr.WATCHLIST)["project_id"])
    if SATELLITE.exists():
        ids |= {p["project_id"] for p in json.loads(SATELLITE.read_text())["projects"]}
    try:
        import grade_california as gc
        ids |= set(gc.verdicts()["project_id"])
    except FileNotFoundError:
        # Without the California files, keep whatever holdout the committed CSV already has.
        if REAL.exists():
            ids |= set(pd.read_csv(REAL).query("holdout")["project_id"])
    return ids


def satellite_gaps():
    """Measured satellite gaps (in %) for projects whose landscape the satellite can measure."""
    if not SATELLITE.exists():
        return {}
    return {p["project_id"]: 100 * p["gap"]
            for p in json.loads(SATELLITE.read_text())["projects"] if p.get("measurable")}


def build(xlsx=vr.DEFAULT_XLSX):
    vrod, vintage_cols = vr.load_vrod(xlsx)
    raw, notes = vr.to_schema(vrod, vintage_cols)
    gaps = satellite_gaps()
    measured = raw["project_id"].isin(gaps)
    raw.loc[measured, "satellite_cover_delta_pct"] = -raw.loc[measured, "project_id"].map(gaps)
    raw["satellite_measured"] = measured
    raw["holdout"] = raw["project_id"].isin(holdout_ids())
    raw = raw.sort_values("project_id").reset_index(drop=True)
    # CRLF on every OS: the published data_hash covers these exact bytes (pandas would use os.linesep).
    raw.to_csv(REAL, index=False, float_format="%.6g", lineterminator="\r\n")
    notes.update({
        "satellite_measured": int(measured.sum()),
        "held_out_from_training": int(raw["holdout"].sum()),
        "citation": vr.CITATION,
        "source_url": vr.VROD_URL,
    })
    REAL_META.write_text(json.dumps(notes, indent=1))
    return raw, notes


if __name__ == "__main__":
    _, notes = build()
    print(json.dumps(notes, indent=1))
