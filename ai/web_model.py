"""
Export the trained risk model to web/sandbox_model.js so the browser sandbox
(web/sandbox.html + web/scorer.js) scores projects with exactly the same model
as the on-chain scores. Nothing is retrained: this reads the saved model file.

Exported:
  - GBM: init constant, learning rate, and every tree's split arrays.
  - IsolationForest: every tree's split arrays, the feature subset each tree
    sees, and a per-leaf path value (depth + average path length of the
    unbuilt subtree - 1), precomputed here exactly as sklearn does.
  - The feature-engineering constants and a few preset projects. Each preset
    carries the score the Python model gives it, which a test checks the
    browser reproduces.
Thresholds and leaf values keep full float64 precision.

Run:  python ai/web_model.py
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble._iforest import _average_path_length

import train_and_score as ts

RAW_FIELDS = ["project_type", "first_vintage", "last_vintage", "est_annual_reductions", "total_issued",
              "total_retired", "max_to_median_issuance", "buffer_pool_pct", "satellite_cover_delta_pct",
              "verifier_changes"]
TYPES = sorted(ts.FORESTRY | ts.LOW_ADDITIONALITY | ts.HISTORY_OF_OVERCREDITING
               | {"Landfill Gas", "Methane Capture (Agriculture)", "Soil Carbon"}) + ["Other"]


def tree_arrays(tree):
    t = tree.tree_
    return {"feature": t.feature.tolist(), "threshold": t.threshold.tolist(),
            "left": t.children_left.tolist(), "right": t.children_right.tolist()}


def export_gbm(gbm):
    trees = []
    for est in gbm.estimators_[:, 0]:
        a = tree_arrays(est)
        a["value"] = est.tree_.value[:, 0, 0].tolist()
        trees.append(a)
    return {"init": float(gbm.init_.constant_[0][0]), "learning_rate": float(gbm.learning_rate), "trees": trees}


def export_iso(iso):
    trees = []
    for est, feats, depths, avg in zip(iso.estimators_, iso.estimators_features_,
                                       iso._decision_path_lengths, iso._average_path_length_per_tree):
        a = tree_arrays(est)
        a["features"] = [int(f) for f in feats]
        # Same expression sklearn adds per tree in _parallel_compute_tree_depths.
        a["path"] = (depths + avg - 1.0).tolist()
        trees.append(a)
    denominator = len(iso.estimators_) * float(_average_path_length([iso._max_samples])[0])
    return {"denominator": denominator, "trees": trees}


def preset_row(r):
    out = {}
    for k in RAW_FIELDS:
        v = r[k]
        out[k] = None if pd.isna(v) else (v if isinstance(v, str) else float(v))
    return out


def closest_to_median(df):
    """The row whose engineered features are nearest its group's median (scaled). A fixed rule, not by score."""
    X = ts.engineer(df)[ts.NUMERIC]
    scale = X.std().replace(0, 1)
    d = ((X - X.median()) / scale).pow(2).sum(axis=1)
    return df.loc[d.idxmin()]


def presets(bundle):
    real = pd.read_csv(ts.REAL)
    out = []

    def add(key, label, note, row, source):
        row = dict(row)
        frame = pd.DataFrame([row])[RAW_FIELDS]
        frame["satellite_cover_delta_pct"] = frame["satellite_cover_delta_pct"].astype(float)
        risk, reasons, _ = ts.score_new(bundle, frame)
        out.append({"key": key, "label": label, "note": note, "source": source, "raw": row,
                    "python_score": int(risk[0]), "python_reasons": reasons[0]})

    sat = json.loads((ts.HERE / "real_world" / "satellite.json").read_text())["projects"]
    measured = {p["project_id"]: p for p in sat if p.get("measurable")}
    for pid, label in (("VCS902", "Kariba REDD+ (Zimbabwe)"), ("VCS944", "Alto Mayo (Peru)"),
                       ("VCS1748", "Southern Cardamom (Cambodia)")):
        r = preset_row(real[real["project_id"] == pid].iloc[0])
        gap = round(100 * measured[pid]["gap"], 1)
        registry_only = {**r, "satellite_cover_delta_pct": None}
        add(pid, f"{label}: registry data only",
            f"Real project ({pid}). What a registry publishes; satellite measurement not applied.",
            registry_only, "Berkeley VROD v2026-08")
        out[-1]["measured_gap_pct"] = gap
        add(pid + "-sat", f"{label}: with satellite measurement",
            f"Real project ({pid}) with our satellite measurement: {gap:.0f}% of claimed avoided loss not observed.",
            {**r, "satellite_cover_delta_pct": -gap}, "Berkeley VROD v2026-08 + Hansen GFC v1.12")
        out[-1]["measured_gap_pct"] = gap

    pool = real[~real["holdout"]]
    for t in ("Wind", "Cookstoves", "Landfill Gas"):
        r = closest_to_median(pool[pool["project_type"] == t].reset_index(drop=True))
        add(f"typical-{t}", f"Typical {t} project",
            f"Real project ({r['project_id']}): the {t} project closest to the median of all {t} projects.",
            preset_row(r), "Berkeley VROD v2026-08")

    syn = pd.read_csv(ts.RAW)
    r = closest_to_median(syn[syn["_archetype"] == "overstated_usage"].reset_index(drop=True))
    add("fictional-overissuer", "Example over-issuer (fictional)",
        "A synthetic project from our training data: issues far more than its own estimate.",
        preset_row(r), "CarbonGuard synthetic data")

    add("blank", "Blank project (start from scratch)", "Typical values; edit anything.",
        {"project_type": "Other", "first_vintage": 2018.0, "last_vintage": 2023.0, "est_annual_reductions": 100000.0,
         "total_issued": 500000.0, "total_retired": 250000.0, "max_to_median_issuance": 1.2,
         "buffer_pool_pct": 0.0, "satellite_cover_delta_pct": None, "verifier_changes": 0.0}, "Blank")
    return out


def export(bundle=None, path=None):
    bundle = bundle or joblib.load(ts.MODEL)
    path = Path(path or ts.WEB_MODEL)
    meta = json.loads(ts.META.read_text())
    model = {
        "generated_by": "ai/web_model.py",
        "model_version": meta["model_version"],
        "model_hash": meta["model_hash"],
        "data_hash": meta["data_hash"],
        "features": bundle["features"],
        "numeric": ts.NUMERIC,
        "current_year": ts.CURRENT_YEAR,
        "forestry": sorted(ts.FORESTRY),
        "low_additionality": sorted(ts.LOW_ADDITIONALITY),
        "history_of_overcrediting": sorted(ts.HISTORY_OF_OVERCREDITING),
        "types": TYPES,
        "high_risk_threshold": 70,
        "clean_baseline": {k: float(v) for k, v in bundle["clean_baseline"].items()},
        "anomaly_range": [float(x) for x in bundle["anomaly_range"]],
        "gbm": export_gbm(bundle["gbm"]),
        "iso": export_iso(bundle["iso"]),
        "presets": presets(bundle),
    }
    # json.dumps writes floats with repr(), which round-trips float64 exactly.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("// Generated by ai/web_model.py - do not edit\nwindow.CG_SANDBOX = "
                    + json.dumps(model, separators=(",", ":"), allow_nan=False) + ";\n")
    return model


if __name__ == "__main__":
    m = export()
    print(f"wrote {ts.WEB_MODEL} ({ts.WEB_MODEL.stat().st_size / 1e6:.2f} MB)")
    for p in m["presets"]:
        print(f"  {p['python_score']:>3}  {p['label']}")
