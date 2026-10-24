"""Tests for the real-world validation on the Berkeley offsets database (VROD)."""
import json

import numpy as np
import pandas as pd
import pytest

from helpers import AI, ts
import validate_real_world as vr

XLSX = vr.DEFAULT_XLSX
SUMMARY = AI / "real_world" / "summary.json"
YEARS = list(range(2015, 2021))


def vrod_rows(rows):
    """Build a tiny frame shaped like the VROD PROJECTS sheet."""
    base = {"Project Name": "x", "Voluntary Registry": "VCS", "Country": "Peru", "Total Credits \nRetired": 0,
            "Total Buffer \nPool Deposits": 0, "First Year of Project (Vintage)": 2015,
            "Estimated Annual Emission Reductions": np.nan}
    out = []
    for r in rows:
        row = {**base, **{y: 0 for y in YEARS}, **r}
        row["Total Credits \nIssued"] = sum(row[y] for y in YEARS)
        out.append(row)
    return pd.DataFrame(out)


def test_schema_mapping_and_neutral_fill_ins():
    vrod = vrod_rows([
        {"Project ID": "A", "Type": "REDD+", 2016: 100, 2017: 100, "Estimated Annual Emission Reductions": 50,
         "Total Buffer \nPool Deposits": 50},
        {"Project ID": "B", "Type": "Wind", 2019: 500},  # one vintage, no estimate
        {"Project ID": "C", "Type": "Biochar", 2018: 10, 2019: 30},  # type the model never saw
        {"Project ID": "D", "Type": "REDD+"},  # never issued -> not scored
    ])
    raw, notes = vr.to_schema(vrod, YEARS)
    assert list(raw["project_id"]) == ["A", "B", "C"]
    a, b, c = (raw.iloc[i] for i in range(3))
    assert (a["first_vintage"], a["last_vintage"]) == (2016, 2017)
    assert a["buffer_pool_pct"] == pytest.approx(20.0)  # 50 / (200 + 50)
    assert b["buffer_pool_pct"] == 0  # buffers only matter for forestry
    assert b["max_to_median_issuance"] == 1.0  # single vintage -> no spike
    assert c["max_to_median_issuance"] == pytest.approx(30 / 20)
    assert (a["project_type"], b["project_type"], c["project_type"]) == ("REDD+", "Wind", "Other")

    X = ts.engineer(raw)
    assert X.loc[0, "over_issuance_ratio"] == pytest.approx(2.0)  # 200 issued vs 50/yr * 2 yrs
    assert X.loc[1, "over_issuance_ratio"] == pytest.approx(1.0)  # no estimate -> neutral
    assert (X["satellite_gap_pct"] == 0).all() and (X["verifier_changes"] == 0).all()
    assert notes["projects_scored"] == 3


def test_fixture_projects_get_valid_scores():
    import joblib
    raw, _ = vr.to_schema(vrod_rows([
        {"Project ID": "A", "Type": "REDD+", 2016: 1000, 2017: 900, "Estimated Annual Emission Reductions": 200},
        {"Project ID": "B", "Type": "Cookstoves", 2019: 500, 2020: 520, "Estimated Annual Emission Reductions": 500},
    ]), YEARS)
    risk, reasons, _ = ts.score_new(joblib.load(ts.MODEL), raw)
    assert ((risk >= 0) & (risk <= 100)).all()
    assert risk[0] > risk[1], "issuing 4.75x the estimate must score above an on-target project"
    assert any("ex-ante estimate" in r for r in reasons[0])


def test_published_real_world_results_come_from_the_current_model():
    summary = json.loads(SUMMARY.read_text())
    meta = json.loads((AI / "model" / "model_meta.json").read_text())
    assert summary["model"] == meta["model_hash"], "rerun python ai/validate_real_world.py"
    assert summary["dataset"]["citation"].startswith("Quartson")
    assert "not allegations" in summary["disclaimer"]


def test_watchlist_entries_cite_a_source():
    for _, w in pd.read_csv(vr.WATCHLIST).iterrows():
        assert w["source_url"].startswith("https://")
        assert 0 < w["official_excess_share"] < 1


def test_published_real_world_scores_are_reproducible_from_the_committed_csv():
    """Runs everywhere (no workbook needed): rescoring data/real_projects.csv gives every published score."""
    import joblib
    raw = pd.read_csv(ts.REAL)
    risk, _, _ = ts.score_new(joblib.load(ts.MODEL), raw)
    published = pd.read_csv(AI / "real_world" / "vrod_scored.csv").set_index("project_id")["risk_score"]
    fresh = pd.Series(risk, index=raw["project_id"])
    assert len(fresh) == len(published)
    assert (fresh.loc[published.index] == published).all()


def test_published_tonnes_by_tier_add_up():
    """The aggregate tonnes figure on the dashboard and story page matches the scored CSV."""
    summary = json.loads(SUMMARY.read_text())
    scored = pd.read_csv(AI / "real_world" / "vrod_scored.csv")
    t = summary["tonnes_by_tier"]
    assert sum(v["projects"] for v in t.values()) == len(scored)
    assert {k: v["projects"] for k, v in t.items()} == summary["tier_counts"]
    assert sum(v["issued_t"] for v in t.values()) == int(scored["total_issued"].sum())
    for v in t.values():
        assert 0 <= v["not_yet_retired_t"] <= v["issued_t"]


def test_judged_projects_are_held_out_of_training():
    """Kariba, satellite-measured and graded California projects must never be trained on."""
    real = pd.read_csv(ts.REAL).set_index("project_id")
    judged = set(pd.read_csv(vr.WATCHLIST)["project_id"])
    judged |= {p["project_id"] for p in json.loads((AI / "real_world" / "satellite.json").read_text())["projects"]}
    grading = AI / "real_world" / "california_grading.json"
    if grading.exists():
        judged |= {p["project_id"] for p in json.loads(grading.read_text())["projects"]}
    assert judged <= set(real.index)
    assert real.loc[sorted(judged), "holdout"].all()
    assert not ts.load_real_training()["project_id"].isin(judged).any()


@pytest.mark.skipif(not XLSX.exists(), reason="VROD workbook not downloaded (see ai/validate_real_world.py)")
def test_committed_real_dataset_matches_the_workbook():
    """Local only: rebuilding from the Berkeley workbook gives exactly the committed CSV."""
    vrod, years = vr.load_vrod(XLSX)
    raw, _ = vr.to_schema(vrod, years)
    assert np.isfinite(ts.engineer(raw).to_numpy()).all()
    committed = pd.read_csv(ts.REAL).set_index("project_id")
    raw = raw.set_index("project_id").loc[committed.index]
    for col in ["total_issued", "total_retired", "first_vintage", "last_vintage", "est_annual_reductions",
                "max_to_median_issuance", "buffer_pool_pct"]:
        np.testing.assert_allclose(raw[col].astype(float), committed[col].astype(float), rtol=1e-5, err_msg=col)
    assert (raw["project_type"] == committed["project_type"]).all()
