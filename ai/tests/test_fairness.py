"""Responsible-AI checks: the model must not treat projects differently by location."""
import numpy as np

from helpers import ts
import fairness

# Synthetic data has no regional effect built in, so any residual is sampling
# noise. Observed max is about 8 points on ~90-150 projects per region.
TOLERANCE = 0.10


def test_country_is_not_a_model_input(run):
    assert not any(c in ("country", "region") for c in run["bundle"]["features"])


def test_moving_every_project_to_another_country_changes_no_score(run):
    raw = run["raw"]
    before, _, _ = ts.score_new(run["bundle"], raw)
    for country in ("USA", "Kenya", "Brazil", "Indonesia"):
        moved = raw.assign(country=country)
        after, _, _ = ts.score_new(run["bundle"], moved)
        np.testing.assert_array_equal(before, after)


def test_no_hidden_regional_bias_beyond_project_type(run):
    report = run["meta"]["fairness"]
    checked = 0
    for region, r in report["regions"].items():
        if r["projects"] < report["min_projects_per_region"] or region == "Other":
            continue
        checked += 1
        assert abs(r["residual"]) <= TOLERANCE, (
            f"{region}: rated High {r['observed_high_rate']:.0%} vs {r['expected_from_type_mix']:.0%} "
            "expected from its project mix"
        )
    assert checked >= 3


def test_report_shape_and_region_mapping(run):
    report = run["meta"]["fairness"]
    assert report["country_is_model_input"] is False
    assert {"overall_high_rate", "max_abs_residual", "regions"} <= report.keys()
    for r in report["regions"].values():
        assert {"projects", "observed_high_rate", "expected_from_type_mix", "residual"} <= r.keys()
    assert fairness.region_of("Brazil") == "Latin America"
    assert fairness.region_of(" kenya ") == "Africa"
    assert fairness.region_of("Atlantis") == "Other"
    # Every country the generator can produce is mapped to a real region.
    assert "Other" not in report["regions"]
