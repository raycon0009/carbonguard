"""The satellite map shows the measured numbers (ai/satellite/make_map.py -> web/satellite_map.js)."""
import base64
import io
import json
import sys

import numpy as np
import pytest

from helpers import AI

sys.path.insert(0, str(AI / "satellite"))
import make_map  # noqa: E402
import measure  # noqa: E402

WEB = AI.parent / "web" / "satellite_map.js"


def load_web():
    text = WEB.read_text()
    return json.loads(text[text.index("=") + 1:].strip().rstrip(";"))


def png(uri):
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))))


def test_downsampling_conserves_every_lost_pixel():
    rng = np.random.default_rng(1)
    loss = rng.integers(0, 25, size=(103, 71)).astype(np.uint8)  # not a multiple of k
    land = rng.choice([0, 1, 2], size=loss.shape, p=[0.05, 0.8, 0.15]).astype(np.uint8)
    counts, land_count = make_map.block_counts(loss, land, k=7)
    assert land_count.sum() == (land == 1).sum()
    for y in range(1, 25):
        assert counts[..., y].sum() == ((loss == y) & (land == 1)).sum()


def test_cell_shading_is_the_share_lost_not_any_loss():
    # One lost pixel out of 100 land pixels must shade the cell 1%, not 100%.
    loss = np.zeros((10, 10), dtype=np.uint8)
    loss[3, 3] = 12
    land = np.ones_like(loss)
    counts, land_count = make_map.block_counts(loss, land, k=10)
    frac = make_map.loss_fractions(counts, land_count)
    assert frac[11, 0, 0] == pytest.approx(0.01)
    assert frac.sum() == pytest.approx(0.01)


def test_water_only_cells_show_no_loss():
    loss = np.full((4, 4), 5, dtype=np.uint8)
    land = np.full((4, 4), 2, dtype=np.uint8)
    counts, land_count = make_map.block_counts(loss, land, k=4)
    assert make_map.loss_fractions(counts, land_count).sum() == 0


def test_block_share():
    mask = np.zeros((6, 6), dtype=bool)
    mask[:3, :3] = True
    assert make_map.block_share(mask, 3).tolist() == [[1, 0], [0, 0]]


def test_square_root_encoding_error_is_bounded():
    f = np.linspace(0, 1, 20001)
    err = np.abs(make_map.decode(make_map.encode(f)) - f)
    # d(f) = 2 sqrt(f) d(s) with |d(s)| <= 0.5/255, plus the second-order term.
    assert (err <= np.sqrt(f) / 255 + 1 / 255 ** 2 / 4 + 1e-12).all()
    assert make_map.decode(make_map.encode(np.array([0.0])))[0] == 0


needs_map = pytest.mark.skipif(not WEB.exists(), reason="run ai/satellite/make_map.py first")
needs_cache = pytest.mark.skipif(not (measure.CACHE / "VCS944_lossyear.npz").exists(),
                                 reason="satellite cache not downloaded (npm run satellite)")


@needs_map
def test_numbers_next_to_the_map_are_the_measured_ones():
    sat = {p["project_id"]: p for p in json.loads(measure.OUT.read_text())["projects"]}
    web = load_web()
    assert {p["project_id"] for p in web["projects"]} == {k for k, v in sat.items() if v["measurable"]}
    assert {p["project_id"] for p in web["not_measurable"]} == {k for k, v in sat.items() if not v["measurable"]}
    for p in web["projects"]:
        s, m = p["stats"], sat[p["project_id"]]
        for key in ("gap", "avoided_ha", "claimed_tco2", "tco2_per_ha_assumed", "crediting_period",
                    "project_loss_ha_by_year", "ring_loss_ha_by_year", "max_supported_share"):
            assert s[key] == m[key], (p["project_id"], key)
        assert s["implied_avoided_ha"] == pytest.approx(m["claimed_tco2"] / m["tco2_per_ha_assumed"])


@needs_map
@needs_cache
def test_map_frames_reproduce_the_full_resolution_satellite_record():
    """Decode what the browser draws and compare it with every 30 m pixel (Alto Mayo, the smallest array)."""
    p = next(p for p in load_web()["projects"] if p["project_id"] == "VCS944")
    loss = np.load(measure.CACHE / "VCS944_lossyear.npz")["data"]
    land = np.load(measure.CACHE / "VCS944_datamask.npz")["data"]
    k, ny, nx = p["cell"], p["height"], p["width"]
    base = png(p["base_png"]).astype(np.float64)
    frames = png(p["loss_png"]).reshape(len(p["years"]), ny, nx)
    land_cells = np.round(base[..., 0] / 255 * k * k)
    _, true_land = make_map.block_counts(loss, land, k)
    for i, year in enumerate(p["years"]):
        frac = make_map.decode(frames[i])
        shown = (frac * land_cells).sum()
        truth = ((loss == year - 2000) & (land == 1)).sum()
        # Bound from the two 8-bit quantisations: loss share and land share.
        bound = (np.sqrt(frac) / 255 * land_cells + frac * (0.5 / 255 * k * k + 0.5)).sum() + 1
        assert abs(shown - truth) <= bound, (year, shown, truth, bound)
    assert np.abs(land_cells - true_land).max() <= 0.5 / 255 * k * k + 0.5
