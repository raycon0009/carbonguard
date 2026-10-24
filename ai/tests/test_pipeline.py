"""
Tests for the CarbonGuard AI pipeline.

Run from the repo root:  python -m pytest ai/tests -q
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score

from helpers import AI, run_pipeline, sha256, ts  # noqa: E402


# ------------------------------------------------------------ reproducibility

def test_two_runs_are_byte_identical(run, tmp_path):
    again = run_pipeline(tmp_path)
    for rel in ("data/projects_raw.csv", "data/projects_scored.csv", "model/carbonguard_risk_v1.joblib"):
        assert sha256(run["dir"] / rel) == sha256(again["dir"] / rel), rel
    assert run["meta"]["model_hash"] == again["meta"]["model_hash"]
    assert run["meta"]["data_hash"] == again["meta"]["data_hash"]


def test_checked_in_hashes_match_checked_in_files():
    """The provenance claim: the hashes written on chain identify the files in this repo."""
    meta = json.loads((AI / "model" / "model_meta.json").read_text())
    assert meta["model_hash"] == sha256(AI / "model" / "carbonguard_risk_v1.joblib")
    assert meta["data_hash"] == ts.data_hash()
    assert meta["data_files"] == [p.name for p in ts.training_files()]


def test_fresh_clone_regenerates_the_published_dataset_and_scores(run):
    meta = json.loads((AI / "model" / "model_meta.json").read_text())
    assert run["meta"]["data_hash"] == meta["data_hash"], "generate_data.py no longer reproduces the training data"
    published = pd.read_csv(AI / "data" / "projects_scored.csv")
    pd.testing.assert_series_equal(run["scored"]["risk_score"], published["risk_score"])


# ------------------------------------------------------------ no leakage

def test_ground_truth_is_never_a_model_input(run):
    X = ts.engineer(run["raw"])
    assert "_archetype" in run["raw"].columns  # the truth exists for evaluation...
    assert not any("archetype" in c for c in X.columns)  # ...but never reaches the model
    assert "_archetype" not in run["bundle"]["features"]
    assert "_archetype" not in run["scored"].columns


# ------------------------------------------------------------ output contract

def test_scores_are_integers_between_0_and_100(run):
    s = run["scored"]["risk_score"]
    assert pd.api.types.is_integer_dtype(s)
    assert s.between(0, 100).all()
    assert len(run["scored"]) == len(run["raw"])


@pytest.mark.parametrize("score,expected", [(0, "Low"), (34, "Low"), (35, "Medium"), (70, "Medium"),
                                            (71, "High"), (100, "High")])
def test_tier_boundaries_match_the_contract_threshold(score, expected):
    # Contract: HIGH_RISK_THRESHOLD = 70 and Flagged when score > 70.
    assert ts.tier(score) == expected


def test_all_three_tiers_occur(run):
    assert set(run["scored"]["risk_tier"]) == {"Low", "Medium", "High"}


def test_reasons_are_well_formed(run):
    for reasons, tier in zip(run["scored"]["reasons"], run["scored"]["risk_tier"]):
        assert isinstance(reasons, str) and reasons
        parts = reasons.split(" | ")
        assert len(parts) <= 3
        assert all(p.strip() for p in parts)
        if tier == "High":
            assert reasons != "No significant red flags", "a frozen batch must say why"


def test_every_cited_reason_points_at_an_abnormal_value(run):
    """Explanations are honest: a reason is only shown when the feature really is abnormal."""
    X = ts.engineer(run["raw"])
    clean = X[ts.weak_labels(X) <= 0.5].median()
    _, _, reasons = ts.explain(run["bundle"]["gbm"], X, clean, run["raw"])
    assert any(reasons)
    for idx, rs in zip(X.index, reasons):
        for text in rs:
            cited = [f for f in X.columns if ts.reason_text(f, X.loc[idx], run["raw"].loc[idx]) == text]
            assert cited, f"unrecognised reason {text!r}"
            assert ts.IS_ABNORMAL[cited[0]](X.at[idx, cited[0]]), f"row {idx}: {text!r} cited for a normal value"


# ------------------------------------------------------------ behaves sensibly

def test_more_over_issuance_never_lowers_risk(run):
    raw, scored = run["raw"], run["scored"]
    clean = raw[scored["risk_tier"] == "Low"].head(40)
    prev = None
    for factor in np.linspace(1, 6, 26):
        r = clean.copy()
        r["total_issued"] = r["total_issued"] * factor
        s = ts.score_features(run["bundle"], ts.engineer(r))
        if prev is not None:
            assert (s >= prev - 1).all(), f"risk dropped when issuance rose to {factor:.1f}x"
        prev = s
    assert (prev > 70).mean() > 0.9, "issuing 6x the estimate should freeze almost every project"


def test_bigger_satellite_gap_never_lowers_risk(run):
    raw, scored = run["raw"], run["scored"]
    forest = raw[(scored["risk_tier"] == "Low") & raw["satellite_cover_delta_pct"].notna()].head(30)
    assert len(forest) > 5
    prev = None
    for gap in range(0, 90, 5):
        r = forest.copy()
        r["satellite_cover_delta_pct"] = -gap
        s = ts.score_features(run["bundle"], ts.engineer(r))
        if prev is not None:
            assert (s >= prev - 1).all(), f"risk dropped when the satellite gap grew to {gap}%"
        prev = s


def test_fixing_the_red_flags_lowers_risk(run):
    raw, scored = run["raw"], run["scored"]
    X = ts.engineer(raw)
    clean_baseline = X[ts.weak_labels(X) <= 0.5].median()
    high = X[scored["risk_tier"] == "High"]
    fixed = high.copy()
    for col in X.columns:
        fixed[col] = clean_baseline[col]
    before = ts.score_features(run["bundle"], high)
    after = ts.score_features(run["bundle"], fixed)
    assert (after < before).all()
    assert (after < 35).all()


def test_dodging_every_rule_does_not_dodge_the_model(run):
    """
    A fraudster who keeps every red flag just under its threshold. No single rule
    fires, but the evidence adds up (noisy-OR + GBM + anomaly detector).
    """
    raw = run["raw"]
    redd = raw[raw["project_type"] == "REDD+"].iloc[[0]].copy()
    years = 8
    redd["first_vintage"], redd["last_vintage"] = 2016, 2016 + years - 1
    redd["est_annual_reductions"] = 100_000
    redd["total_issued"] = int(1.45 * 100_000 * years)  # rule fires at 1.5x
    redd["satellite_cover_delta_pct"] = -28  # rule fires at 30%
    redd["max_to_median_issuance"] = 2.9  # rule fires at 3.0x
    redd["buffer_pool_pct"] = 12.5  # rule fires at a 3-point shortfall
    redd["verifier_changes"] = 1  # rule fires at 2
    redd["total_retired"] = int(redd["total_issued"].iloc[0] * 0.21)  # rule fires below 20%

    X = ts.engineer(redd)
    rules_fired = [
        X["over_issuance_ratio"].iloc[0] > 1.5,
        X["satellite_gap_pct"].iloc[0] > 30,
        X["issuance_spike"].iloc[0] > 3.0,
        X["buffer_shortfall"].iloc[0] > 3,
        X["verifier_changes"].iloc[0] > 1.5,
        X["retirement_rate"].iloc[0] < 0.2,
    ]
    assert not any(rules_fired), "the evasive project should dodge every individual rule"
    score = ts.score_features(run["bundle"], X)[0]
    # Trained on synthetic data alone this scored High (79). Since adding 6,000 real
    # projects it scores Medium (~65): still flagged for review, no longer frozen.
    assert score >= 35, f"evasive project scored {score}; it should at least be flagged (Medium)"


def test_satellite_evidence_alone_raises_risk(run):
    """
    An inflated baseline hides behind an inflated estimate: issuance looks normal
    and only outside evidence reveals it. Satellite evidence must move the score
    on its own (the model used to ignore it - see README, real-world validation).
    """
    raw, scored = run["raw"], run["scored"]
    redd = raw[(raw["project_type"] == "REDD+") & (scored["risk_tier"] == "Low")].head(10)
    assert len(redd) >= 3
    no_gap = ts.score_features(run["bundle"], ts.engineer(redd.assign(satellite_cover_delta_pct=0)))
    big_gap = ts.score_features(run["bundle"], ts.engineer(redd.assign(satellite_cover_delta_pct=-70)))
    assert (big_gap - no_gap >= 25).all(), list(zip(no_gap, big_gap))
    assert (big_gap >= 35).all(), "a 70% satellite gap alone should at least trigger a warning"


# ------------------------------------------------------------ robustness

def test_bad_input_rows_still_get_a_valid_score(run):
    raw = run["raw"]
    r = raw.head(5).copy()
    r.loc[r.index[0], "est_annual_reductions"] = 0  # used to divide by zero
    r.loc[r.index[1], "total_issued"] = 0
    r.loc[r.index[2], "satellite_cover_delta_pct"] = np.nan
    r.loc[r.index[3], "project_type"] = "Space Mirrors"  # type the model never saw
    r.loc[r.index[4], "first_vintage"] = r.loc[r.index[4], "last_vintage"] = 2025  # single vintage
    X = ts.engineer(r)
    assert np.isfinite(X.values).all()
    s = ts.score_features(run["bundle"], X)
    assert np.isfinite(s).all() and ((s >= 0) & (s <= 100)).all()
    assert s[0] > 70, "issuing credits against a zero estimate should be high risk"


# ------------------------------------------------------------ generalisation

@pytest.mark.parametrize("seed", [1, 42, 777])
def test_model_generalises_to_freshly_generated_markets(seed, tmp_path):
    """Retrain on a different random market; the model must still separate problem projects."""
    r = run_pipeline(tmp_path, seed=seed)
    truth = (r["raw"]["_archetype"] != "clean").astype(int)
    auc = roc_auc_score(truth, r["scored"]["risk_score"])
    assert auc >= 0.9, f"seed {seed}: AUC {auc:.3f}"
    high = r["scored"]["risk_tier"] == "High"
    assert truth[high].mean() >= 0.85, f"seed {seed}: High-tier precision {truth[high].mean():.2f}"


def test_score_new_agrees_with_training_scores(run):
    """Scoring the training rows as if they were new gives (nearly) the published scores.
    Training scores are out-of-fold, so small differences are expected."""
    risk, reasons, _ = ts.score_new(run["bundle"], run["raw"])
    diff = np.abs(risk - run["scored"]["risk_score"].to_numpy())
    assert np.median(diff) <= 3
    agree = (np.array([ts.tier(r) for r in risk]) == run["scored"]["risk_tier"].to_numpy()).mean()
    assert agree >= 0.9, f"tiers agree on only {agree:.0%} of projects"
    assert len(reasons) == len(risk)


def test_reported_metrics_match_a_fresh_run(run):
    published = json.loads((AI / "model" / "model_meta.json").read_text())["metrics"]
    for k, v in published.items():
        assert run["meta"]["metrics"][k] == pytest.approx(v, abs=0.005), k
