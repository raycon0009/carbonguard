"""
CarbonGuard risk model.

Pipeline
  1. Feature engineering on registry-style project data.
  2. Weak supervision: documented red-flag rules -> noisy "suspicious" labels.
  3. GradientBoostingClassifier learns from the weak labels (generalises the
     rules, smooths thresholds).  IsolationForest catches anomalies the rules
     never described.  Blend -> 0-100 risk score -> Low / Medium / High tier.
  4. Counterfactual explanations: for each project, reset one feature to the
     typical clean-project value and measure how much the risk drops.  The
     top-3 drops become human-readable reasons that are written on chain.
  5. SHA-256 of the model file and the input data are written to
     model_meta.json so the contract can record exactly which model scored
     which credit (AI provenance).

Training data: the 420 synthetic projects (the only ones with ground truth
and satellite evidence) plus every real registry project in
data/real_projects.csv except the held-out ones (see build_real_dataset.py).

Run:  python ai/train_and_score.py
"""
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, IsolationForest
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import KFold, cross_val_predict

from fairness import fairness_report, plot_fairness

HERE = Path(__file__).parent
RAW = HERE / "data" / "projects_raw.csv"
REAL = HERE / "data" / "real_projects.csv"
SCORED = HERE / "data" / "projects_scored.csv"
MODEL = HERE / "model" / "carbonguard_risk_v1.joblib"
META = HERE / "model" / "model_meta.json"
WEB_MODEL = HERE.parent / "web" / "sandbox_model.js"  # browser copy of the model (web_model.py)
CHARTS = HERE / "charts"
CURRENT_YEAR = 2026
MODEL_VERSION = "cg-risk-v1"

FORESTRY = {"REDD+", "Afforestation/Reforestation", "Improved Forest Management",
            "Blue Carbon (Mangroves)"}
LOW_ADDITIONALITY = {"Industrial Gas (HFC-23/N2O)", "Large Hydro", "Wind", "Solar"}
HISTORY_OF_OVERCREDITING = {"REDD+", "Cookstoves", "Improved Forest Management"}

NUMERIC = ["over_issuance_ratio", "satellite_gap_pct", "issuance_spike", "vintage_age",
           "retirement_rate", "buffer_shortfall", "verifier_changes"]


def sha256_file(path):
    return "0x" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def training_files():
    return [p for p in (RAW, REAL) if p.exists()]


def data_hash():
    """SHA-256 of all training data: the synthetic file, then the real-project file."""
    h = hashlib.sha256()
    for p in training_files():
        h.update(Path(p).read_bytes())
    return "0x" + h.hexdigest()


def load_real_training():
    """Real registry projects used for training (held-out projects excluded)."""
    if not REAL.exists():
        return pd.DataFrame()
    real = pd.read_csv(REAL)
    return real[~real["holdout"]].reset_index(drop=True)


def engineer(df):
    f = pd.DataFrame(index=df.index)
    years = (df["last_vintage"] - df["first_vintage"] + 1).clip(lower=1)
    f["over_issuance_ratio"] = df["total_issued"] / (df["est_annual_reductions"] * years).clip(lower=1)
    # positive = satellite sees LESS avoided deforestation than the project claims
    f["satellite_gap_pct"] = (-df["satellite_cover_delta_pct"]).fillna(0).clip(lower=0)
    f["issuance_spike"] = df["max_to_median_issuance"]
    f["vintage_age"] = CURRENT_YEAR - df["first_vintage"]
    f["retirement_rate"] = df["total_retired"] / df["total_issued"].clip(lower=1)
    is_forest = df["project_type"].isin(FORESTRY)
    # forestry projects should hold >= 15% of credits in a non-permanence buffer
    f["buffer_shortfall"] = np.where(is_forest, (15 - df["buffer_pool_pct"]).clip(lower=0), 0)
    f["verifier_changes"] = df["verifier_changes"]
    f["type_overcrediting_history"] = df["project_type"].isin(HISTORY_OF_OVERCREDITING).astype(int)
    f["type_low_additionality"] = df["project_type"].isin(LOW_ADDITIONALITY).astype(int)
    return f


def _soft(x, threshold, width):
    """Smooth 0..1 evidence that x exceeds threshold (sigmoid instead of a hard cut)."""
    return 1 / (1 + np.exp(-(x - threshold) / width))


def weak_labels(f):
    """
    Snorkel-style weak supervision. Each labelling function encodes a red flag
    from the literature and returns soft evidence in [0, 1]; they are combined
    with a noisy-OR into P(suspicious).  No fraud ground truth is used.
    """
    lfs = {
        # (evidence, reliability weight)
        "over_issuance": (_soft(f["over_issuance_ratio"], 1.5, 0.2), 0.85),
        "satellite_gap": (_soft(f["satellite_gap_pct"], 30, 6), 0.80),
        "issuance_spike": (_soft(f["issuance_spike"], 3.0, 0.4), 0.45),
        "old_low_additionality": (_soft(f["vintage_age"], 14, 1.0) * f["type_low_additionality"], 0.70),
        "buffer": (_soft(f["buffer_shortfall"], 3, 1.0), 0.35),
        "auditor_churn": (_soft(f["verifier_changes"], 1.5, 0.3), 0.30),
        "dumping": (_soft(-f["retirement_rate"], -0.2, 0.05), 0.30),
    }
    not_suspicious = np.ones(len(f))
    for evidence, w in lfs.values():
        not_suspicious *= 1 - w * evidence
    return pd.Series(1 - not_suspicious, index=f.index)


# A feature is only cited as a reason when its value is actually abnormal.
IS_ABNORMAL = {
    "over_issuance_ratio": lambda v: v > 1.2,
    "satellite_gap_pct": lambda v: v > 15,
    "issuance_spike": lambda v: v > 2.2,
    "vintage_age": lambda v: v > 12,
    "retirement_rate": lambda v: v < 0.35,
    "buffer_shortfall": lambda v: v > 0,
    "verifier_changes": lambda v: v >= 2,
    "type_overcrediting_history": lambda v: v == 1,
    "type_low_additionality": lambda v: v == 1,
}


def reason_text(feature, row, raw):
    v = row[feature]
    return {
        "over_issuance_ratio": f"Issued {v:.1f}x its own ex-ante estimate",
        "satellite_gap_pct": f"Satellite shows {v:.0f}% less avoided forest loss than claimed",
        "issuance_spike": f"Issuance spike: peak year {v:.1f}x the median year",
        "vintage_age": f"Old vintage ({int(raw['first_vintage'])}) - weak additionality",
        "retirement_rate": f"Only {v:.0%} of credits ever retired - possible dumping",
        "buffer_shortfall": f"Thin permanence buffer ({raw['buffer_pool_pct']:.0f}% vs 15% norm)",
        "verifier_changes": f"Auditor changed {int(v)} times",
        "type_overcrediting_history": f"{raw['project_type']} has documented over-crediting",
        "type_low_additionality": f"{raw['project_type']} rarely needs carbon finance",
    }[feature]


def explain(model, X, clean_baseline, raw, top_k=3, min_effect=0.03):
    """Counterfactual attribution: risk drop when one feature is set to the clean median."""
    p = model.predict(X)
    effects = pd.DataFrame(index=X.index, columns=X.columns, dtype=float)
    for col in X.columns:
        Xc = X.copy()
        Xc[col] = clean_baseline[col]
        effects[col] = p - model.predict(Xc)
    reasons = []
    for i, idx in enumerate(X.index):
        ranked = effects.loc[idx].sort_values(ascending=False)
        abnormal = ranked[np.array([IS_ABNORMAL[c](X.at[idx, c]) for c in ranked.index])]
        top = abnormal[abnormal > min_effect].head(top_k)
        if top.empty and p[i] >= 0.5:
            # Several red flags at once saturate the score: removing any single one
            # barely moves it. Cite the abnormal features it relies on together.
            top = abnormal.head(top_k)
        reasons.append([reason_text(c, X.loc[idx], raw.loc[idx]) for c in top.index])
    return p, effects, reasons


def tier(score):
    return "High" if score > 70 else "Medium" if score >= 35 else "Low"


def blend(p_suspicious, anomaly):
    """The published score formula: 80% learned P(suspicious), 20% anomaly, 0-100."""
    return np.round(100 * (0.8 * np.clip(p_suspicious, 0, 1) + 0.2 * np.clip(anomaly, 0, 1))).astype(int).clip(0, 100)


def anomaly_of(bundle, X):
    lo, hi = bundle["anomaly_range"]
    return (-bundle["iso"].score_samples(X[NUMERIC]) - lo) / (hi - lo)


def score_features(bundle, X):
    """Risk 0-100 for already-engineered feature rows the model has never seen."""
    X = X[bundle["features"]]
    return blend(bundle["gbm"].predict(X), anomaly_of(bundle, X))


def score_new(bundle, raw):
    """Score raw registry-style project rows. Returns (risk, reasons, features)."""
    X = engineer(raw)[bundle["features"]]
    p, _, reasons = explain(bundle["gbm"], X, bundle["clean_baseline"], raw)
    return blend(p, anomaly_of(bundle, X)), reasons, X


def main():
    raw = pd.read_csv(RAW)
    real = load_real_training()
    n_syn = len(raw)
    X_syn = engineer(raw)
    X = pd.concat([X_syn, engineer(real)], ignore_index=True) if len(real) else X_syn
    y_soft = weak_labels(X)
    y = (y_soft > 0.5).astype(int)
    # Equal total weight per data source: the 420 synthetic projects are the only
    # ones with satellite evidence and ground truth, so 6,000 real projects must
    # not drown them out.
    weight = np.ones(len(X))
    if len(real):
        weight[:n_syn] = len(real) / n_syn

    gbm = GradientBoostingRegressor(n_estimators=200, max_depth=3, learning_rate=0.05,
                                    subsample=0.8, min_samples_leaf=8, random_state=7)
    # out-of-fold predictions: each project is scored by a model that never saw it
    cv = KFold(n_splits=5, shuffle=True, random_state=7)
    p_oof = np.clip(cross_val_predict(gbm, X, y_soft, cv=cv, params={"sample_weight": weight}), 0, 1)
    gbm.fit(X, y_soft, sample_weight=weight)

    iso = IsolationForest(n_estimators=300, contamination="auto", random_state=7)
    iso.fit(X[NUMERIC])
    raw_anomaly = -iso.score_samples(X[NUMERIC])
    anomaly_range = (float(raw_anomaly.min()), float(raw_anomaly.max()))
    anomaly = (raw_anomaly - anomaly_range[0]) / (anomaly_range[1] - anomaly_range[0])

    clean_baseline = X[y == 0].median()
    # Scores, explanations and metrics below are for the synthetic demo projects.
    _, effects, reasons = explain(gbm, X_syn, clean_baseline, raw)
    y_syn, p_syn = y[:n_syn], p_oof[:n_syn]

    risk = blend(p_syn, anomaly[:n_syn])

    out = raw.drop(columns=["_archetype"], errors="ignore").copy()
    out["risk_score"] = risk
    out["risk_tier"] = [tier(s) for s in risk]
    out["reasons"] = [" | ".join(r) if r else "No significant red flags" for r in reasons]
    for k in ("over_issuance_ratio", "satellite_gap_pct", "retirement_rate"):
        out[k] = X_syn[k].round(3)
    out.to_csv(SCORED, index=False, lineterminator="\r\n")  # same bytes on every OS
    out.to_json(SCORED.with_suffix(".json"), orient="records", indent=1)

    MODEL.parent.mkdir(parents=True, exist_ok=True)
    bundle = {"gbm": gbm, "iso": iso, "features": list(X.columns),
              "anomaly_range": anomaly_range, "clean_baseline": clean_baseline}
    joblib.dump(bundle, MODEL)

    # Evaluation. Weak-label agreement is not accuracy; the hidden archetype
    # column (synthetic ground truth, never a model input) is the honest test.
    metrics = {"weak_label_positive_rate": round(float(y_syn.mean()), 3),
               "oof_auc_vs_weak_labels": round(float(roc_auc_score(y_syn, p_syn)), 3)}
    if "_archetype" in raw:
        truth = (raw["_archetype"] != "clean").astype(int)
        metrics["auc_vs_hidden_truth_blended"] = round(float(roc_auc_score(truth, risk)), 3)
        metrics["auc_vs_hidden_truth_rules_only"] = round(float(roc_auc_score(truth, y_syn)), 3)
        flagged = out["risk_tier"] == "High"
        metrics["high_tier_precision"] = round(float(truth[flagged].mean()), 3)
        metrics["recall_high_or_medium"] = round(float((out["risk_tier"] != "Low")[truth == 1].mean()), 3)

    meta = {
        "model_version": MODEL_VERSION,
        "model_hash": sha256_file(MODEL),
        "data_hash": data_hash(),
        "data_files": [p.name for p in training_files()],
        "source_weighting": "equal total weight for synthetic and real projects",
        "training_rows": {"synthetic": n_syn, "real": len(real),
                          "real_held_out": int(pd.read_csv(REAL)["holdout"].sum()) if REAL.exists() else 0},
        "features": list(X.columns),
        "score_formula": "round(100 * (0.8 * GBM(weak-supervised P(suspicious)) + 0.2 * isolation_anomaly))",
        "tiers": {"Low": "<35", "Medium": "35-70", "High": ">70 (blocked from trading on chain)"},
        "metrics": metrics,
        "tier_counts": out["risk_tier"].value_counts().to_dict(),
        "global_importance": dict(sorted(
            ((c, round(float(v), 4)) for c, v in zip(X.columns, gbm.feature_importances_)),
            key=lambda kv: -kv[1])),
    }
    meta["fairness"] = fairness_report(out)
    META.write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    from web_model import export as export_web_model  # imports this module, so not at the top
    export_web_model(bundle, WEB_MODEL)
    make_charts(out, meta)


def make_charts(out, meta):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    CHARTS.mkdir(exist_ok=True)
    colors = {"Low": "#2e9e6b", "Medium": "#e0a526", "High": "#d64545"}

    ct = pd.crosstab(out["project_type"], out["risk_tier"]).reindex(columns=["Low", "Medium", "High"], fill_value=0)
    ct = ct.loc[ct.sum(axis=1).sort_values().index]
    ax = ct.plot.barh(stacked=True, color=[colors[c] for c in ct.columns], figsize=(9, 5.5), width=0.75)
    ax.set_xlabel("Projects")
    ax.set_ylabel("")
    ax.set_title("CarbonGuard risk tier by project type")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    plt.tight_layout()
    plt.savefig(CHARTS / "risk_by_type.png", dpi=160)
    plt.close()

    imp = pd.Series(meta["global_importance"]).sort_values()
    ax = imp.plot.barh(color="#3b6fd6", figsize=(8, 4.5), width=0.7)
    ax.set_title("What drives the risk score (model feature importance)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    plt.tight_layout()
    plt.savefig(CHARTS / "risk_drivers.png", dpi=160)
    plt.close()

    plot_fairness(meta["fairness"], CHARTS / "fairness_by_region.png")


if __name__ == "__main__":
    main()
