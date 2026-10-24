"""
Fairness check: does CarbonGuard treat projects in some regions more harshly?

Country is never a model input, so the model cannot discriminate by location
directly. It could still do so indirectly, because project types are not
spread evenly (most REDD+ is in tropical countries). So for every region we
compare:

  observed  - share of the region's projects the model rated High
  expected  - the High rate we would expect from the region's project-type mix
              alone (each project counted at its type's overall High rate)
  residual  - observed - expected: the part that project type does not
              explain. Close to zero means no hidden regional bias.
"""
import pandas as pd

REGIONS = {
    "Latin America": ["Argentina", "Belize", "Bolivia", "Brazil", "Chile", "Colombia", "Costa Rica",
                      "Dominican Republic", "Ecuador", "El Salvador", "Guatemala", "Guyana", "Honduras",
                      "Mexico", "Nicaragua", "Panama", "Paraguay", "Peru", "Suriname", "Uruguay", "Venezuela"],
    "Africa": ["Angola", "Benin", "Burkina Faso", "Burundi", "Cameroon", "Congo", "DRC",
               "Democratic Republic of the Congo", "Republic of the Congo", "Cote d'Ivoire", "Ethiopia",
               "Gabon", "Ghana", "Guinea", "Kenya", "Liberia", "Madagascar", "Malawi", "Mali", "Morocco",
               "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda", "Senegal", "Sierra Leone",
               "South Africa", "Sudan", "Tanzania", "Togo", "Uganda", "Zambia", "Zimbabwe", "Egypt"],
    "Asia": ["Bangladesh", "Cambodia", "China", "India", "Indonesia", "Laos", "Malaysia", "Mongolia",
             "Myanmar", "Nepal", "Pakistan", "Papua New Guinea", "Philippines", "South Korea", "Korea",
             "Sri Lanka", "Taiwan", "Thailand", "Turkey", "Uzbekistan", "Vietnam", "Viet Nam", "Kazakhstan"],
    "North America": ["USA", "United States", "Canada"],
    "Europe": ["Bulgaria", "Denmark", "France", "Germany", "Ireland", "Netherlands", "Norway", "Poland",
               "Portugal", "Romania", "Spain", "Sweden", "Switzerland", "United Kingdom", "Ukraine"],
    "Oceania": ["Australia", "New Zealand", "Fiji"],
}
COUNTRY_TO_REGION = {c.lower(): r for r, cs in REGIONS.items() for c in cs}
MIN_PROJECTS = 10


def region_of(country):
    return COUNTRY_TO_REGION.get(str(country).strip().lower(), "Other")


def fairness_report(scored):
    """scored needs columns country, project_type, risk_tier. Returns a JSON-able dict."""
    df = scored[["country", "project_type", "risk_tier"]].copy()
    df["region"] = df["country"].map(region_of)
    df["high"] = (df["risk_tier"] == "High").astype(float)
    type_rate = df.groupby("project_type")["high"].mean()
    df["expected"] = df["project_type"].map(type_rate)

    regions = {}
    for region, g in df.groupby("region"):
        observed, expected = float(g["high"].mean()), float(g["expected"].mean())
        regions[region] = {
            "projects": int(len(g)),
            "observed_high_rate": round(observed, 3),
            "expected_from_type_mix": round(expected, 3),
            "residual": round(observed - expected, 3),
        }
    big = {r: v for r, v in regions.items() if v["projects"] >= MIN_PROJECTS and r != "Other"}
    return {
        "method": "residual = observed High rate - High rate expected from the region's project-type mix",
        "country_is_model_input": False,
        "overall_high_rate": round(float(df["high"].mean()), 3),
        "max_abs_residual": round(max((abs(v["residual"]) for v in big.values()), default=0.0), 3),
        "min_projects_per_region": MIN_PROJECTS,
        "regions": dict(sorted(regions.items(), key=lambda kv: -kv[1]["projects"])),
    }


def plot_fairness(report, path, title="High-risk rate by region"):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    rows = {r: v for r, v in report["regions"].items() if v["projects"] >= report["min_projects_per_region"]}
    if not rows:
        return
    frame = pd.DataFrame(rows).T[["observed_high_rate", "expected_from_type_mix"]] * 100
    frame.columns = ["Observed", "Expected from project-type mix"]
    ax = frame.plot.barh(color=["#d64545", "#9aa3ad"], figsize=(8.5, 4.5), width=0.75)
    ax.set_xlabel("% of projects rated High")
    ax.set_ylabel("")
    ax.set_title(f"{title}\n(gap = what project type does not explain; max {report['max_abs_residual'] * 100:.1f} pts)")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
