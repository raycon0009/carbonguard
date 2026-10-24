"""
Real-world validation: score every real carbon project in the Berkeley Voluntary
Registry Offsets Database (VROD), and check where projects with publicly
confirmed over-crediting land.

Projects used to judge the model (the watch list, satellite-measured projects,
graded California projects) are held out of training, so their scores are
out-of-sample. VROD does not publish two of our inputs (satellite forest-cover
gap, auditor changes); where we have no satellite measurement those are filled
with neutral values that can only LOWER a score - a conservative test.

Reads data/real_projects.csv (built from the workbook by build_real_dataset.py),
so anyone can reproduce these results without downloading the workbook.

Data: Quartson, Haya, Bernard, Abayo, Rong, So, Elias (2026). Voluntary Registry
Offsets Database v2026-08, Berkeley Carbon Trading Project, University of
California, Berkeley. CC BY 4.0.
https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database

Run:  python ai/validate_real_world.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

import train_and_score as ts
from fairness import fairness_report, plot_fairness

HERE = Path(__file__).parent
DEFAULT_XLSX = HERE / "data" / "external" / "VROD-v2026-08.xlsx"
OUT = HERE / "real_world"
WEB = HERE.parent / "web" / "real_world.js"
WATCHLIST = OUT / "watchlist.csv"
CITATION = ("Quartson, Haya, Bernard, Abayo, Rong, So, Elias (2026). Voluntary Registry Offsets Database "
            "v2026-08, Berkeley Carbon Trading Project, UC Berkeley. CC BY 4.0.")
VROD_URL = "https://gspp.berkeley.edu/berkeley-carbon-trading-project/offsets-database"
# West et al., Science 2023: ~94% of credits from the REDD+ projects studied were not additional.
WEST_2023_NOT_REAL = 0.94

# VROD "Type" -> the project types the model was trained on. Anything else is
# scored as an unseen type ("Other"), which carries no type-based penalty.
TYPE_MAP = {
    "REDD+": "REDD+",
    "Jurisdictional REDD+": "REDD+",
    "Avoided Forest Conversion": "REDD+",
    "Afforestation/Reforestation": "Afforestation/Reforestation",
    "Improved Forest Management": "Improved Forest Management",
    "Cookstoves": "Cookstoves",
    "Wind": "Wind",
    "Solar - Centralized": "Solar",
    "Solar - centralized": "Solar",
    "Solar - Distributed": "Solar",
    "Hydropower": "Large Hydro",
    "Landfill Methane": "Landfill Gas",
    "HFC23 Destruction": "Industrial Gas (HFC-23/N2O)",
    "N2O Destruction in Nitric Acid Production": "Industrial Gas (HFC-23/N2O)",
    "N2O Destruction in Adipic Acid Production": "Industrial Gas (HFC-23/N2O)",
    "Wetland Restoration": "Blue Carbon (Mangroves)",
    "Avoided Grassland Conversion": "Soil Carbon",
    "Sustainable Grassland Management": "Soil Carbon",
    "Sustainable Agriculture": "Soil Carbon",
    "Manure Methane Digester": "Methane Capture (Agriculture)",
    "Biodigesters": "Methane Capture (Agriculture)",
}
RAW_COLS = ["project_id", "project_type", "country", "first_vintage", "last_vintage", "est_annual_reductions",
            "total_issued", "total_retired", "max_to_median_issuance", "buffer_pool_pct",
            "satellite_cover_delta_pct", "verifier_changes"]
NEUTRAL = {
    "satellite_cover_delta_pct": np.nan,  # not published -> no satellite gap
    "verifier_changes": 0,  # only the current verifier is published
}


def load_vrod(xlsx):
    """Read the PROJECTS sheet: identity columns, totals, buffer, and issuance by vintage year."""
    head = pd.read_excel(xlsx, sheet_name="PROJECTS", header=3, nrows=0)
    cols = list(head.columns)
    named = ["Project ID", "Project Name", "Voluntary Registry", "Type", "Country",
             "Total Credits \nIssued", "Total Credits \nRetired", "Total Buffer \nPool Deposits",
             "First Year of Project (Vintage)", "Estimated Annual Emission Reductions"]
    missing = [c for c in named if c not in cols]
    if missing:
        raise SystemExit(f"VROD layout changed, missing columns: {missing}")
    # The first block of integer-year columns is "credits issued by vintage year".
    start = cols.index("First Year of Project (Vintage)") + 1
    positions = []
    for i in range(start, len(cols)):
        if not isinstance(cols[i], (int, np.integer)):
            break
        positions.append(i)
    vintage_cols = [cols[i] for i in positions]
    # Select by position: later blocks reuse the same year headers.
    df = pd.read_excel(xlsx, sheet_name="PROJECTS", header=3,
                       usecols=[cols.index(c) for c in named] + positions)
    df = df[df["Project ID"].notna()].reset_index(drop=True)
    return df, vintage_cols


def to_schema(vrod, vintage_cols):
    """Map VROD rows to the model's raw input schema. Returns (raw, notes)."""
    issued_by_vintage = vrod[vintage_cols].apply(pd.to_numeric, errors="coerce").fillna(0).clip(lower=0)
    total_issued = pd.to_numeric(vrod["Total Credits \nIssued"], errors="coerce").fillna(0)
    keep = (total_issued > 0) & (issued_by_vintage.sum(axis=1) > 0)
    v, ibv = vrod[keep].reset_index(drop=True), issued_by_vintage[keep].reset_index(drop=True)
    years = np.array(vintage_cols)
    nonzero = ibv.to_numpy() > 0
    first = np.array([years[r].min() for r in nonzero])
    last = np.array([years[r].max() for r in nonzero])

    def spike(row):
        vals = row[row > 0]
        return float(vals.max() / np.median(vals)) if len(vals) >= 2 else 1.0

    issued = pd.to_numeric(v["Total Credits \nIssued"], errors="coerce").fillna(0)
    est = pd.to_numeric(v["Estimated Annual Emission Reductions"], errors="coerce")
    has_est = est.notna() & (est > 0)
    n_years = np.maximum(last - first + 1, 1)
    # No published estimate -> neutral: pretend issuance matched it exactly (ratio 1.0).
    est = est.where(has_est, issued / n_years)

    project_type = v["Type"].map(TYPE_MAP).fillna("Other")
    buffer = pd.to_numeric(v["Total Buffer \nPool Deposits"], errors="coerce").fillna(0)
    is_forest = project_type.isin(ts.FORESTRY)
    buffer_pct = np.where(is_forest, 100 * buffer / (issued + buffer).clip(lower=1), 0.0)

    raw = pd.DataFrame({
        "project_id": v["Project ID"].astype(str),
        "project_name": v["Project Name"].astype(str),
        "registry": v["Voluntary Registry"].astype(str),
        "vrod_type": v["Type"].astype(str),
        "project_type": project_type,
        "country": v["Country"].astype(str),
        "first_vintage": first,
        "last_vintage": last,
        "est_annual_reductions": est,
        "total_issued": issued,
        "total_retired": pd.to_numeric(v["Total Credits \nRetired"], errors="coerce").fillna(0),
        "max_to_median_issuance": [spike(r) for r in ibv.to_numpy()],
        "buffer_pool_pct": buffer_pct,
        **NEUTRAL,
    })
    notes = {
        "projects_in_vrod": int(len(vrod)),
        "projects_scored": int(len(raw)),
        "share_with_published_estimate": round(float(has_est.mean()), 3),
        "share_mapped_to_known_type": round(float((project_type != "Other").mean()), 3),
        "neutral_fill_ins": {
            "satellite_gap": "not published by registries -> 0 (no penalty)",
            "verifier_changes": "only current verifier published -> 0 (no penalty)",
            "over_issuance_ratio": "1.0 (no penalty) when no ex-ante estimate is published",
        },
    }
    return raw, notes


def percentile(scores, value):
    """Share of scores strictly below value (0-100)."""
    scores = np.asarray(scores)
    return round(100 * float((scores < value).mean()), 1)


def satellite_what_if(bundle, row, gap_pct):
    """Score a project as if satellite data showed the given gap. A what-if, not a detection."""
    r = row.to_frame().T.infer_objects()
    r["satellite_cover_delta_pct"] = -gap_pct
    risk, reasons, _ = ts.score_new(bundle, r.reset_index(drop=True))
    return {"satellite_gap_pct": round(gap_pct, 1), "risk_score": int(risk[0]), "risk_tier": ts.tier(risk[0])}


def satellite_section(scored, bundle):
    """Measured satellite results, with each project's score with and without them."""
    path = HERE / "real_world" / "satellite.json"
    if not path.exists():
        return []
    rows = []
    for m in json.loads(path.read_text())["projects"]:
        hit = scored[scored["project_id"] == m["project_id"]]
        if hit.empty:
            continue
        r = hit.iloc[0]
        registry_only = r[RAW_COLS].to_frame().T.infer_objects().reset_index(drop=True)
        registry_only["satellite_cover_delta_pct"] = np.nan
        before, before_reasons, _ = ts.score_new(bundle, registry_only)
        rows.append({
            "project_id": m["project_id"],
            "name": m["name"],
            "measurable": bool(m.get("measurable")),
            "not_measurable_reason": m.get("not_measurable_reason"),
            "gap": m["gap"],
            "max_supported_share": m.get("max_supported_share"),
            "break_even_tco2_per_ha": m.get("break_even_tco2_per_ha"),
            "tco2_per_ha_assumed": m["tco2_per_ha_assumed"],
            "crediting_period": m["crediting_period"],
            "project_loss_rate_pre": m["project_loss_rate_pre"],
            "claimed_tco2": m["claimed_tco2"],
            "avoided_ha": m["avoided_ha"],
            "score_registry_only": int(before[0]),
            "reasons_registry_only": " | ".join(before_reasons[0]) if before_reasons[0] else "No significant red flags",
            "score_with_satellite": int(r["risk_score"]),
            "tier_with_satellite": r["risk_tier"],
            "reasons": r["reasons"],
        })
    return rows


def summarise(scored, watchlist, notes, bundle):
    redd = scored[scored["project_type"] == "REDD+"]
    flagged_redd_tonnes = redd.loc[redd["risk_tier"] != "Low", "total_issued"].sum()
    watch = []
    for _, w in watchlist.iterrows():
        hit = scored[scored["project_id"] == w["project_id"]]
        if hit.empty:
            watch.append({"project_id": w["project_id"], "found_in_vrod": False})
            continue
        r = hit.iloc[0]
        watch.append({
            "project_id": r["project_id"],
            "project_name": w["project_name"],
            "finding": w["finding"],
            "source": w["source"],
            "source_url": w["source_url"],
            "found_in_vrod": True,
            "risk_score": int(r["risk_score"]),
            "risk_tier": r["risk_tier"],
            "reasons": r["reasons"],
            "percentile_among_redd": percentile(redd["risk_score"], r["risk_score"]),
            "percentile_among_all": percentile(scored["risk_score"], r["risk_score"]),
            "over_issuance_ratio": round(float(r["over_issuance_ratio"]), 2),
            # What the score would be if satellite data showed the gap the official review found.
            "what_if_satellite": satellite_what_if(bundle, r[RAW_COLS], 100 * float(w["official_excess_share"])),
        })
    tiers = scored["risk_tier"].value_counts().reindex(["Low", "Medium", "High"], fill_value=0)
    # Tonnes behind each tier, aggregate only (no project is named). "Not yet retired" is what is still sellable.
    unretired = (scored["total_issued"] - scored["total_retired"]).clip(lower=0)
    tonnes = {t: {"projects": int((scored["risk_tier"] == t).sum()),
                  "issued_t": int(scored.loc[scored["risk_tier"] == t, "total_issued"].sum()),
                  "not_yet_retired_t": int(unretired[scored["risk_tier"] == t].sum())}
              for t in ("Low", "Medium", "High")}
    by_type = (scored.groupby("project_type")
               .agg(projects=("risk_score", "size"), median_score=("risk_score", "median"),
                    high_share=("risk_tier", lambda t: round(float((t == "High").mean()), 3)))
               .sort_values("median_score", ascending=False))
    return {
        "dataset": {"name": "Berkeley Voluntary Registry Offsets Database v2026-08", "url": VROD_URL,
                    "citation": CITATION, **notes},
        "model": json.loads((ts.META).read_text())["model_hash"],
        "tier_counts": {k: int(v) for k, v in tiers.items()},
        "tonnes_by_tier": tonnes,
        "watchlist": watch,
        "satellite": satellite_section(scored, bundle),
        "redd_vs_west_2023": {
            "redd_projects_scored": int(len(redd)),
            "share_of_redd_tonnes_rated_medium_or_high": round(float(flagged_redd_tonnes / redd["total_issued"].sum()), 3),
            "west_2023_share_not_real": WEST_2023_NOT_REAL,
            "note": "Different project samples; a directional comparison, not a like-for-like test.",
        },
        "by_type": by_type.reset_index().to_dict(orient="records"),
        "fairness": fairness_report(scored),
        "disclaimer": "Scores are statistical risk indicators from public registry data, not allegations of wrongdoing.",
    }


def plot(scored, summary, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    redd = scored[scored["project_type"] == "REDD+"]["risk_score"]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.hist(scored["risk_score"], bins=range(0, 102, 3), color="#c9d1d9", label=f"All {len(scored):,} real projects")
    ax.hist(redd, bins=range(0, 102, 3), color="#e0a526", label=f"REDD+ ({len(redd)})")
    for w in summary["watchlist"]:
        if w.get("found_in_vrod"):
            ax.axvline(w["risk_score"], color="#d64545", lw=2)
            ax.annotate(f"{w['project_name']}\nscore {w['risk_score']}", (w["risk_score"], ax.get_ylim()[1] * 0.85),
                        xytext=(-8, 0), textcoords="offset points", ha="right", color="#d64545", fontsize=9)
    ax.axvline(70.5, color="#555", ls="--", lw=1)
    ax.text(71.5, ax.get_ylim()[1] * 0.5, "frozen on chain >70", color="#555", fontsize=8)
    ax.set_xlabel("CarbonGuard risk score")
    ax.set_ylabel("Projects")
    ax.set_title("Real registry projects scored by CarbonGuard")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="upper center")
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()


def main():
    if not ts.REAL.exists():
        raise SystemExit("Run python ai/build_real_dataset.py first (needs the VROD workbook once).")
    bundle = joblib.load(ts.MODEL)
    raw = pd.read_csv(ts.REAL)
    notes = json.loads((ts.REAL.parent / "real_projects_meta.json").read_text())
    risk, reasons, X = ts.score_new(bundle, raw)

    scored = raw.copy()
    scored["risk_score"] = risk
    scored["risk_tier"] = [ts.tier(s) for s in risk]
    scored["reasons"] = [" | ".join(r) if r else "No significant red flags" for r in reasons]
    scored["over_issuance_ratio"] = X["over_issuance_ratio"].round(3).to_numpy()

    summary = summarise(scored, pd.read_csv(WATCHLIST), notes, bundle)
    OUT.mkdir(exist_ok=True)
    scored.drop(columns=["verifier_changes"]).sort_values("risk_score", ascending=False).to_csv(
        OUT / "vrod_scored.csv", index=False)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    ts.CHARTS.mkdir(exist_ok=True)
    plot(scored, summary, ts.CHARTS / "real_world_scores.png")
    plot_fairness(summary["fairness"], ts.CHARTS / "fairness_real_world.png", "Real projects: High-risk rate by region")
    WEB.write_text("// Generated by ai/validate_real_world.py\nwindow.CG_REAL_WORLD = "
                   + json.dumps({k: summary[k] for k in ("dataset", "tier_counts", "tonnes_by_tier", "watchlist", "satellite", "redd_vs_west_2023", "disclaimer")}, indent=1)
                   + ";\n")
    print(json.dumps({k: summary[k] for k in ("tier_counts", "watchlist", "satellite", "redd_vs_west_2023")}, indent=2))
    print("fairness max residual:", summary["fairness"]["max_abs_residual"])
    return summary


if __name__ == "__main__":
    main()
