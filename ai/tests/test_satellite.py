"""Tests for the satellite measurement of avoided deforestation (ai/satellite/measure.py)."""
import json
import math
import sys

import pytest

from helpers import AI

sys.path.insert(0, str(AI / "satellite"))
import measure  # noqa: E402

YEARS = range(2001, 2025)
DENSITY = 300.0


def flat(rate_by_year, land_ha):
    """{year: hectares lost} for a given per-year loss rate function."""
    return {y: rate_by_year(y) * land_ha for y in YEARS}


def test_a_project_that_changed_nothing_earned_nothing():
    # Same 1%/yr loss inside and outside, before and after the project started.
    loss = flat(lambda y: 0.01, 1000)
    r = measure.estimate_gap(loss, 1000, loss, 1000, 2011, 2019, claimed_tco2=50_000, density=DENSITY)
    assert r["avoided_ha"] == pytest.approx(0)
    assert r["gap"] == 1.0
    assert r["break_even_tco2_per_ha"] == math.inf


def test_a_project_that_stopped_deforestation_earns_its_credits():
    # Project drops from 1%/yr to 0 at the start; the surroundings keep losing 1%/yr.
    project = flat(lambda y: 0.01 if y < 2011 else 0.0, 1000)
    ring = flat(lambda y: 0.01, 5000)
    avoided_ha = 0.01 * 1000 * 9  # 9 crediting years, 2011-2019
    r = measure.estimate_gap(project, 1000, ring, 5000, 2011, 2019, avoided_ha * DENSITY, DENSITY)
    assert r["avoided_ha"] == pytest.approx(avoided_ha)
    assert r["gap"] == pytest.approx(0)
    assert r["break_even_tco2_per_ha"] == pytest.approx(DENSITY)


def test_over_crediting_shows_up_as_the_share_not_backed_by_avoided_loss():
    project = flat(lambda y: 0.01 if y < 2011 else 0.0, 1000)
    ring = flat(lambda y: 0.01, 5000)
    real = 0.01 * 1000 * 9 * DENSITY
    r = measure.estimate_gap(project, 1000, ring, 5000, 2011, 2019, claimed_tco2=4 * real, density=DENSITY)
    assert r["gap"] == pytest.approx(0.75)  # 3 of every 4 credits are not backed
    # Stopping all expected loss would support exactly the real credits: 1/4 of the claim.
    assert r["max_supported_share"] == pytest.approx(0.25)


def test_a_regional_slowdown_is_not_credited_to_the_project():
    # Deforestation fell everywhere at the same time: the project did nothing special.
    falling = lambda y: 0.02 if y < 2011 else 0.005  # noqa: E731
    r = measure.estimate_gap(flat(falling, 1000), 1000, flat(falling, 5000), 5000, 2011, 2019, 10_000, DENSITY)
    assert r["avoided_ha"] == pytest.approx(0, abs=1e-9)
    assert r["gap"] == pytest.approx(1.0)


def test_the_reported_gap_is_the_more_favourable_of_two_methods():
    # Remote project: barely deforested even before it started; the surroundings lose 1%/yr.
    project = flat(lambda y: 0.001, 1000)
    ring = flat(lambda y: 0.01, 5000)
    claim = 0.01 * 1000 * 9 * DENSITY  # credits as if it would otherwise be cleared like its surroundings
    r = measure.estimate_gap(project, 1000, ring, 5000, 2011, 2019, claim, DENSITY)
    assert r["gap_before_after"] == pytest.approx(1.0)  # nothing changed inside the project
    assert r["gap_surroundings"] == pytest.approx(0.1)  # 0.9 of the surroundings' loss avoided
    assert r["method_used"] == "surroundings" and r["gap"] == pytest.approx(0.1)


def test_a_landscape_the_satellite_cannot_see_is_not_measurable():
    # Shrubland: almost no tree-cover loss is ever detected, so there is no baseline to compare.
    tiny = flat(lambda y: 1e-6, 100_000)
    r = measure.estimate_gap(tiny, 100_000, tiny, 400_000, 2010, 2019, 1_000_000, DENSITY)
    assert r["measurable"] is False
    assert "cannot see" in r["not_measurable_reason"]
    enough = flat(lambda y: 0.001, 100_000)  # 100 ha/yr -> 900 ha over 2001-2009... still under 1,000
    assert measure.estimate_gap(enough, 100_000, enough, 400_000, 2010, 2019, 1, DENSITY)["measurable"] is False
    more = flat(lambda y: 0.002, 100_000)  # 200 ha/yr -> 1,800 ha before the project
    assert measure.estimate_gap(more, 100_000, more, 400_000, 2010, 2019, 1, DENSITY)["measurable"] is True


def test_years_after_the_satellite_record_are_ignored():
    loss = flat(lambda y: 0.01, 1000)
    r = measure.estimate_gap(loss, 1000, loss, 1000, 2015, 2031, 1, DENSITY)
    assert r["crediting_period"] == [2015, measure.LAST_YEAR]


def test_hansen_tile_names():
    assert [t[0] for t in measure.tile_names((27.0, -18.6, 30.4, -15.9))] == ["10S_020E", "10S_030E"]
    assert [t[0] for t in measure.tile_names((-77.9, -6.1, -77.1, -5.4))] == ["00N_080W"]
    assert [t[0] for t in measure.tile_names((102.9, 11.1, 104.1, 12.0))] == ["20N_100E"]


def test_carbon_densities_are_ordered_and_plausible():
    d = {z: measure.tco2_per_ha(z) for z in measure.AGB}
    assert d["dry"] < d["moist"] < d["montane"] < d["rain"]
    assert 150 < d["dry"] < 400 and 400 < d["rain"] < 800


def test_published_satellite_results_are_well_formed():
    path = AI / "real_world" / "satellite.json"
    if not path.exists():
        pytest.skip("run python ai/satellite/measure.py first")
    data = json.loads(path.read_text())
    assert {"satellite", "boundaries", "carbon_density", "credits"} <= data["sources"].keys()
    for p in data["projects"]:
        assert 0 <= p["gap"] <= 1
        assert p["project_land_ha"] > 0 and p["ring_land_ha"] > 0
        assert p["boundary_type"] == "Official"
        assert p["crediting_period"][1] <= measure.LAST_YEAR
        assert p["measurable"] == (p["project_loss_ha_pre"] >= measure.MIN_PRE_LOSS_HA)
