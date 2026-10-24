"""
Grade CarbonGuard against independent, published verdicts: the project-level
over-crediting estimates for California's forest offsets program.

Badgley, Freeman, Hamman, Haya, Trugman, Anderegg, Cullenward (2021).
Systematic over-crediting in California's forest carbon offsets program.
Global Change Biology 28(4):1433-1445. doi:10.1111/gcb.15943.
Data: CarbonPlan (carbonplan.blob.core.windows.net/carbonplan-retro), CC BY 4.0.

The grading rule was fixed before looking at any result:
  - over-credited = the 5th percentile of the study's 1,000 simulated
    over-crediting estimates is above zero (over-credited even on the most
    favourable estimate);
  - also reported: rank correlation between CarbonGuard's risk score and the
    median share of credits found to be over-credited.
These projects are held out of training (see build_real_dataset.py), so every
score here comes from a model that never saw the project.

Run:  python ai/grade_california.py
"""
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

HERE = Path(__file__).parent
SRC = HERE / "data" / "external" / "california"
SCORED = HERE / "real_world" / "vrod_scored.csv"
OUT = HERE / "real_world" / "california_grading.json"
CITATION = ("Badgley et al. (2021) Systematic over-crediting in California's forest carbon offsets program. "
            "Global Change Biology 28:1433-1445. Data: CarbonPlan, CC BY 4.0.")


def vrod_id(opr_id):
    """California offset IDs -> Berkeley database IDs (ACR numbers are zero-padded there)."""
    m = re.fullmatch(r"ACR(\d+)", opr_id)
    return f"ACR{int(m.group(1)):04d}" if m else opr_id


def verdicts():
    """Per project: median and 90% range of the over-credited share of its credits."""
    errors = json.loads((SRC / "reclassification-crediting-error.json").read_text())
    projects = {p["opr_id"]: p for p in json.loads((SRC / "retro-db-light-v1.0.json").read_text())}
    rows = []
    for opr_id, sims in errors.items():
        credits = projects[opr_id]["arbocs"]["calculated"]
        if not credits:
            continue
        share = np.asarray(sims["delta_arbocs"]) / credits
        rows.append({
            "opr_id": opr_id,
            "project_id": vrod_id(opr_id),
            "name": projects[opr_id]["name"],
            "credits": credits,
            "overcredited_share_median": float(np.median(share)),
            "overcredited_share_p05": float(np.percentile(share, 5)),
            "overcredited_share_p95": float(np.percentile(share, 95)),
        })
    v = pd.DataFrame(rows)
    v["overcredited"] = v["overcredited_share_p05"] > 0
    return v


def grade():
    v = verdicts()
    scored = pd.read_csv(SCORED)[["project_id", "risk_score", "risk_tier", "reasons"]]
    graded = v.merge(scored, on="project_id", how="inner")
    y, s = graded["overcredited"].astype(int), graded["risk_score"]
    auc = float(roc_auc_score(y, s)) if y.nunique() == 2 else None
    rho, p = spearmanr(s, graded["overcredited_share_median"])
    by_tier = (graded.groupby("risk_tier")
               .agg(projects=("risk_score", "size"),
                    overcredited=("overcredited", "sum"),
                    median_overcredited_share=("overcredited_share_median", "median"))
               .reindex(["Low", "Medium", "High"]).dropna(how="all"))
    result = {
        "source": CITATION,
        "rule": "over-credited = 5th percentile of the study's simulated over-crediting > 0 (fixed before grading)",
        "projects_in_study": int(len(v)),
        "projects_matched": int(len(graded)),
        "unmatched_ids": sorted(set(v["project_id"]) - set(graded["project_id"])),
        "overcredited": int(y.sum()),
        "auc": None if auc is None else round(auc, 3),
        "spearman_rho": round(float(rho), 3),
        "spearman_p": round(float(p), 4),
        "by_tier": {t: {"projects": int(r["projects"]), "overcredited": int(r["overcredited"]),
                        "median_overcredited_share": round(float(r["median_overcredited_share"]), 3)}
                    for t, r in by_tier.iterrows()},
        "projects": graded.sort_values("risk_score", ascending=False).round(4).to_dict(orient="records"),
    }
    OUT.write_text(json.dumps(result, indent=1))
    return result


if __name__ == "__main__":
    r = grade()
    print(json.dumps({k: r[k] for k in r if k != "projects"}, indent=2))
