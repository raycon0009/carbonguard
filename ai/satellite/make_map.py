"""
Turn the satellite measurement into pictures: an animated map of real forest
loss, year by year, for each measured REDD+ project.

Reads the cached Hansen arrays that measure.py already downloaded (nothing is
fetched) and the official boundaries, and writes:
  - web/satellite_map.js        data for web/satellite.html (animated canvas map)
  - docs/media/<id>_timelapse.gif   the same animation for videos and the README

Honest shading: the map is downsampled ~16x, so each map cell covers ~250
satellite pixels. A cell is shaded by the SHARE of its land that was lost (on a
square-root scale so small losses stay visible), never "red if any pixel was
lost", which would exaggerate loss up to 250x.

Every number shown next to the map comes from ai/real_world/satellite.json.
Run:  python ai/satellite/make_map.py       (needs requirements-satellite.txt)
"""
import base64
import io
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import measure  # noqa: E402

ROOT = HERE.parents[1]
WEB = ROOT / "web" / "satellite_map.js"
MEDIA = ROOT / "docs" / "media"
YEARS = list(range(2001, measure.LAST_YEAR + 1))
MAX_SIDE = 1000  # map cells on the long side
SIMPLIFY_CELLS = 0.6  # outline simplification, in map cells


# ----------------------------------------------------------------- pure maths

def block_counts(loss, land, k):
    """
    Per k x k block: land-pixel count, and land pixels lost in each year.
    Returns (counts[ny, nx, 1 + n_years], land_count[ny, nx]); counts[..., 0] is
    land never lost. Exact: the counts sum to the full-resolution totals.
    """
    n = len(YEARS) + 1
    h, w = loss.shape
    ny, nx = math.ceil(h / k), math.ceil(w / k)
    counts = np.zeros((ny, nx, n), dtype=np.int64)
    col_block = np.arange(w) // k
    for by in range(ny):
        ls, ld = loss[by * k:(by + 1) * k], land[by * k:(by + 1) * k] == 1
        keys = (np.broadcast_to(col_block, ls.shape)[ld] * n + np.minimum(ls[ld], n - 1)).astype(np.int64)
        counts[by] = np.bincount(keys, minlength=nx * n).reshape(nx, n)
    return counts, counts.sum(axis=2)


def block_share(mask, k):
    """Share of each k x k block covered by a boolean mask."""
    h, w = mask.shape
    ny, nx = math.ceil(h / k), math.ceil(w / k)
    padded = np.zeros((ny * k, nx * k), dtype=np.float32)
    padded[:h, :w] = mask
    return padded.reshape(ny, k, nx, k).mean(axis=(1, 3))


def encode(frac):
    """Share 0..1 -> uint8 on a square-root scale (more precision for small losses)."""
    return np.round(255 * np.sqrt(np.clip(frac, 0, 1))).astype(np.uint8)


def decode(u8):
    return (np.asarray(u8, dtype=np.float64) / 255) ** 2


def loss_fractions(counts, land_count):
    """[year, ny, nx] share of each block's land lost in that year."""
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = counts[..., 1:] / land_count[..., None]
    return np.nan_to_num(frac).transpose(2, 0, 1)


# ----------------------------------------------------------------- I/O

def png_uri(arr):
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def outline(geom, left, top, k):
    """Polygon rings in map-cell coordinates, simplified to ~half a cell."""
    import shapely
    from shapely.affinity import affine_transform

    cell = measure.RES * k
    g = affine_transform(geom, [1 / cell, 0, 0, -1 / cell, -left / cell, top / cell])
    g = shapely.simplify(g, SIMPLIFY_CELLS)
    polys = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
    rings = []
    for p in polys:
        if p.is_empty or p.area < 1:
            continue
        for r in [p.exterior, *p.interiors]:
            rings.append([[round(x, 1), round(y, 1)] for x, y, *_ in r.coords])
    return rings


def build_project(pid, result):
    """All map data for one project. Uses only cached satellite arrays."""
    import shapely
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin

    feature = json.loads((measure.BOUNDARIES / f"{pid}.geojson").read_text())
    project, ring = measure.regions(shapely.geometry.shape(feature["geometry"]))
    cache = {layer: np.load(measure.CACHE / f"{pid}_{layer}.npz") for layer in ("lossyear", "datamask")}
    loss, land = cache["lossyear"]["data"], cache["datamask"]["data"]
    left, top = float(cache["lossyear"]["left"]), float(cache["lossyear"]["top"])
    k = math.ceil(max(loss.shape) / MAX_SIDE)

    counts, land_count = block_counts(loss, land, k)
    frac = loss_fractions(counts, land_count)
    transform = from_origin(left, top, measure.RES, measure.RES)
    in_project = block_share(~geometry_mask([project], out_shape=loss.shape, transform=transform), k)
    in_ring = block_share(~geometry_mask([ring], out_shape=loss.shape, transform=transform), k)
    land_share = land_count / float(k * k)

    ny, nx = land_count.shape
    mid_lat = top - loss.shape[0] * measure.RES / 2
    km_x = k * measure.RES * 111.320 * math.cos(math.radians(mid_lat))
    km_y = k * measure.RES * 110.574
    base = np.dstack([np.round(255 * land_share).astype(np.uint8),
                      np.round(255 * in_project).astype(np.uint8),
                      np.round(255 * in_ring).astype(np.uint8)])
    frames = encode(frac).reshape(len(YEARS) * ny, nx)  # years stacked vertically

    density = result["tco2_per_ha_assumed"]
    stats = {k_: result[k_] for k_ in ("name", "gap", "method_used", "max_supported_share", "claimed_tco2",
                                       "tco2_per_ha_assumed", "avoided_ha", "crediting_period", "pre_period",
                                       "project_land_ha", "ring_land_ha", "project_loss_ha_by_year",
                                       "ring_loss_ha_by_year", "issued_in_window", "forest_zone")}
    stats["implied_avoided_ha"] = result["claimed_tco2"] / density
    data = {
        "project_id": pid, "width": nx, "height": ny, "cell": k, "years": YEARS,
        "km_per_cell": [round(km_x, 5), round(km_y, 5)],
        "base_png": png_uri(base), "loss_png": png_uri(frames), "encoding": "sqrt",
        "project_outline": outline(project, left, top, k), "ring_outline": outline(ring, left, top, k),
        "stats": stats,
    }
    arrays = {"frac": frac, "land_share": land_share, "in_project": in_project, "in_ring": in_ring,
              "counts": counts, "loss": loss, "land": land}
    return data, arrays


# ----------------------------------------------------------------- GIF

FADE = 0.6  # how much the area outside the comparison ring is faded
LIGHT = {"land": (238, 242, 238), "water": (198, 218, 236), "project": (205, 235, 220), "ring": (228, 236, 230),
         "loss": (196, 61, 61), "text": "#13201a", "muted": "#5c6b63", "brand": "#0d7a55", "high": "#c43d3d"}


def composite(arrays, upto):
    """RGB image of cumulative loss up to and including year index `upto`."""
    a = arrays
    rgb = np.empty(a["land_share"].shape + (3,), dtype=np.float64)
    water = a["land_share"] < 0.5
    for i, c in enumerate(LIGHT["land"]):
        rgb[..., i] = c
    for key in ("ring", "project"):
        m = a["in_" + key] > 0.5
        rgb[m] = LIGHT[key]
    rgb[water] = LIGHT["water"]
    cum = decode(encode(a["frac"][: upto + 1])).sum(axis=0) if upto >= 0 else 0 * a["land_share"]
    alpha = np.clip(np.sqrt(cum), 0, 1)[..., None]
    rgb = rgb * (1 - alpha) + np.array(LIGHT["loss"]) * alpha
    # Outside the project and its 2-20 km comparison ring: shown, but faded.
    outside = (a["in_project"] < 0.5) & (a["in_ring"] < 0.5)
    rgb[outside] = rgb[outside] * (1 - FADE) + 255 * FADE
    return rgb.astype(np.uint8)


def make_gif(data, arrays, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    s = data["stats"]
    start, end = s["crediting_period"]
    kx, ky = data["km_per_cell"]
    aspect = ky / kx
    frames = []
    for i, year in enumerate(YEARS):
        fig = plt.figure(figsize=(9.6, 5.4), dpi=90)
        ax = fig.add_axes([0.01, 0.04, 0.6, 0.86])
        ax.imshow(composite(arrays, i), aspect=aspect, interpolation="nearest")
        for rings, color, lw in ((data["ring_outline"], LIGHT["muted"], 0.6), (data["project_outline"], LIGHT["brand"], 1.4)):
            for r in rings:
                xy = np.array(r)
                ax.plot(xy[:, 0] - 0.5, xy[:, 1] - 0.5, color=color, lw=lw)
        # Area the credits imply was saved, to scale (bottom-left corner, not a location).
        side_km = math.sqrt(s["implied_avoided_ha"] / 100)
        w, h = side_km / kx, side_km / ky
        x0, y0 = data["width"] * 0.03, data["height"] * 0.97
        ax.add_patch(plt.Rectangle((x0, y0 - h), w, h, fill=False, ec=LIGHT["high"], lw=1.6, ls="--"))
        ax.text(x0 + w + data["width"] * 0.01, y0 - h / 2, "area the credits imply\nwas saved (to scale,\nnot a location)",
                fontsize=7, color=LIGHT["high"], va="center",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none", alpha=0.85))
        ax.set_xlim(-0.5, data["width"] - 0.5)
        ax.set_ylim(data["height"] - 0.5, -0.5)
        ax.axis("off")

        in_credit = start <= year <= end
        fig.text(0.01, 0.94, f"{s['name']} ({data['project_id']})", fontsize=13, weight="bold", color=LIGHT["text"])
        fig.text(0.64, 0.84, str(year), fontsize=34, weight="bold", color=LIGHT["high"] if in_credit else LIGHT["text"])
        fig.text(0.64, 0.79, f"crediting period {start}-{end}" + ("  (now)" if in_credit else ""), fontsize=9,
                 color=LIGHT["muted"])
        lost = sum(v for y, v in s["project_loss_ha_by_year"].items() if int(y) <= year)
        lines = [
            ("Tree-cover loss inside the project so far", f"{lost:,.0f} ha", LIGHT["text"]),
            (f"Credits issued ({start}-{end})", f"{s['claimed_tco2'] / 1e6:.1f}M t CO2", LIGHT["text"]),
            (f"Forest that would have to be saved\n(at a high-end {s['tco2_per_ha_assumed']:.0f} t CO2/ha)",
             f"{s['implied_avoided_ha']:,.0f} ha", LIGHT["high"]),
            ("Loss actually avoided, per satellite\n(most favourable method)", f"{s['avoided_ha']:,.0f} ha", LIGHT["brand"]),
            ("Credits not backed by avoided loss", f"{s['gap']:.0%}", LIGHT["high"]),
        ]
        y = 0.68
        for label, value, color in lines:
            fig.text(0.64, y, label, fontsize=8.5, color=LIGHT["muted"], va="top")
            fig.text(0.985, y, value, fontsize=11, weight="bold", color=color, ha="right", va="top")
            y -= 0.115
        fig.text(0.01, 0.01, "Red = tree-cover loss (Hansen Global Forest Change v1.12, 30 m), shaded by share of each cell lost. "
                 "Green outline: project; grey: 2-20 km comparison ring; beyond it faded.", fontsize=6.5, color=LIGHT["muted"])
        fig.canvas.draw()
        frames.append(Image.fromarray(np.asarray(fig.canvas.buffer_rgba())[..., :3]))
        plt.close(fig)
    pal = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT) for f in frames]
    durations = [450] * len(pal)
    durations[-1] = 3000
    path.parent.mkdir(parents=True, exist_ok=True)
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=durations, loop=0, optimize=True)


def main():
    sat = json.loads((measure.OUT).read_text())
    out = {"sources": sat["sources"], "method": sat["method"], "projects": [], "not_measurable": []}
    for r in sat["projects"]:
        pid = r["project_id"]
        if not r.get("measurable"):
            out["not_measurable"].append({"project_id": pid, "name": r["name"], "reason": r["not_measurable_reason"]})
            continue
        if not (measure.CACHE / f"{pid}_lossyear.npz").exists():
            print(f"{pid}: no cached satellite data, skipped (run npm run satellite first)")
            continue
        data, arrays = build_project(pid, r)
        out["projects"].append(data)
        gif = MEDIA / f"{pid}_timelapse.gif"
        make_gif(data, arrays, gif)
        print(f"{pid}: {data['width']}x{data['height']} cells of {data['cell']}x{data['cell']} px; "
              f"gif {gif.stat().st_size / 1e6:.1f} MB", flush=True)
    order = {"VCS902": 0, "VCS944": 1, "VCS1748": 2}
    out["projects"].sort(key=lambda p: order.get(p["project_id"], 9))
    WEB.write_text("// Generated by ai/satellite/make_map.py - do not edit\nwindow.CG_SAT = "
                   + json.dumps(out, separators=(",", ":")) + ";\n")
    print(f"wrote {WEB} ({WEB.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
