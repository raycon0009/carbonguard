"""
Generate a realistic sample of voluntary carbon-market projects.

The columns mirror the public Berkeley Carbon Trading Project "Voluntary
Registry Offsets Database" (registry, project type, methodology, country,
vintages, credits issued / retired, buffer pool).  Values are SYNTHETIC but
the problem archetypes are calibrated to published findings:

  * REDD+ over-crediting  - West et al., Science 2023; Guardian/Zeit 2023
                            (~90%+ of sampled rainforest credits "phantom")
  * Cookstove over-crediting - Gill-Wiehl et al., Nature Sustainability 2024
                            (credits overstated ~10x on average)
  * Old industrial-gas / large-hydro vintages - low additionality, flagged
    by ICVCM Core Carbon Principles and CORSIA vintage cut-offs.

Two extra columns that registries do NOT publish today are simulated to show
what CarbonGuard would ingest from external data:
  * satellite_cover_delta_pct - claimed vs. satellite-observed avoided forest
    loss (forestry only).  In production: Global Forest Watch / Hansen data.
  * verifier_changes          - number of times the auditor changed.
"""
import numpy as np
import pandas as pd
from pathlib import Path

RNG = np.random.default_rng(2026)
OUT = Path(__file__).parent / "data" / "projects_raw.csv"

# project_type: (registry weights, methodologies, countries, share, mean annual tCO2e)
TYPES = {
    "REDD+": (["VCS"], ["VM0007", "VM0009", "VM0015"],
              ["Brazil", "Peru", "Indonesia", "Zimbabwe", "Cambodia", "DRC", "Colombia"], 0.16, 900_000),
    "Afforestation/Reforestation": (["VCS", "GS", "ACR"], ["AR-ACM0003", "VM0047"],
              ["India", "Uganda", "Kenya", "Brazil", "USA", "Mexico"], 0.10, 120_000),
    "Improved Forest Management": (["ACR", "CAR", "VCS"], ["IFM-ACR", "CAR-FPP", "VM0012"],
              ["USA", "Canada", "Chile"], 0.08, 300_000),
    "Cookstoves": (["GS", "VCS"], ["GS-TPDDTEC", "VMR0006", "AMS-II.G"],
              ["Kenya", "Ghana", "Malawi", "Rwanda", "Uganda", "India", "Nigeria"], 0.13, 80_000),
    "Wind": (["VCS", "GS"], ["ACM0002"], ["India", "China", "Turkey", "Brazil", "Vietnam"], 0.12, 200_000),
    "Solar": (["VCS", "GS"], ["ACM0002", "AMS-I.D"], ["India", "China", "Vietnam", "Chile"], 0.08, 110_000),
    "Large Hydro": (["VCS"], ["ACM0002"], ["China", "India", "Brazil", "Laos"], 0.06, 400_000),
    "Landfill Gas": (["ACR", "CAR", "VCS"], ["ACM0001", "CAR-LFG"], ["USA", "Brazil", "Mexico", "Chile"], 0.08, 150_000),
    "Industrial Gas (HFC-23/N2O)": (["VCS", "ACR"], ["AM0001", "AM0021"], ["China", "India", "USA"], 0.04, 1_500_000),
    "Blue Carbon (Mangroves)": (["VCS"], ["VM0033"], ["Kenya", "Indonesia", "Colombia", "Senegal"], 0.04, 60_000),
    "Soil Carbon": (["VCS", "CAR"], ["VM0042", "CAR-SEP"], ["USA", "Australia", "Brazil"], 0.05, 70_000),
    "Methane Capture (Agriculture)": (["GS", "VCS"], ["AMS-III.D"], ["Mexico", "Vietnam", "Thailand"], 0.06, 50_000),
}
NAME_WORDS = ["Green", "River", "Highland", "Sun", "Coastal", "Valley", "Savanna", "Delta",
              "Northern", "Lake", "Summit", "Forest", "Clear", "Horizon", "Evergreen", "Blue"]
CURRENT_YEAR = 2026
REGISTRY_PREFIX = {"VCS": "VCS", "GS": "GS", "ACR": "ACR", "CAR": "CAR"}


def make_project(i, ptype):
    regs, meths, countries, _, mean_vol = TYPES[ptype]
    registry = RNG.choice(regs)
    first_vintage = int(RNG.integers(2006, 2023))
    years = int(min(CURRENT_YEAR - 1 - first_vintage, RNG.integers(3, 14)))
    years = max(years, 1)
    last_vintage = first_vintage + years - 1
    est_annual = float(RNG.lognormal(np.log(mean_vol), 0.5))

    # Baseline: an honest project issues ~70-105% of its ex-ante estimate.
    over_credit = RNG.uniform(0.7, 1.05)
    spike = RNG.uniform(1.0, 1.8)
    sat_delta = np.nan
    verifier_changes = int(RNG.poisson(0.4))
    buffer_pct = 0.0
    archetype = "clean"

    forestry = ptype in ("REDD+", "Afforestation/Reforestation",
                         "Improved Forest Management", "Blue Carbon (Mangroves)")
    if forestry:
        buffer_pct = float(np.clip(RNG.normal(18, 4), 8, 30))
        sat_delta = float(RNG.normal(-5, 8))  # % gap: observed vs claimed avoided loss

    # --- inject documented failure archetypes -------------------------------
    r = RNG.random()
    if ptype == "REDD+" and r < 0.55:
        archetype = "inflated_baseline"
        sat_delta = float(RNG.uniform(-85, -40))
        if RNG.random() < 0.5:
            # Baseline inflated at registration (the Kariba / West et al. pattern):
            # the ex-ante estimate is inflated too, so issuance looks normal
            # against it and only outside evidence (satellite) reveals the gap.
            over_credit = RNG.uniform(0.75, 1.1)
        else:
            over_credit = RNG.uniform(1.8, 6.0)
            spike = RNG.uniform(2.5, 7.0)
            buffer_pct = float(RNG.uniform(6, 12))
            verifier_changes = int(RNG.integers(1, 4))
    elif ptype == "Cookstoves" and r < 0.45:
        archetype = "overstated_usage"
        over_credit = RNG.uniform(2.0, 9.0)
        spike = RNG.uniform(2.0, 5.0)
    elif ptype in ("Industrial Gas (HFC-23/N2O)", "Large Hydro") and r < 0.6:
        archetype = "non_additional_old_vintage"
        first_vintage = int(RNG.integers(2006, 2013))
        last_vintage = first_vintage + years - 1
        over_credit = RNG.uniform(1.0, 1.6)
    elif ptype in ("Wind", "Solar") and r < 0.25:
        archetype = "non_additional_old_vintage"
        first_vintage = int(RNG.integers(2006, 2014))
        last_vintage = first_vintage + years - 1
    elif ptype == "Improved Forest Management" and r < 0.25:
        archetype = "inflated_baseline"
        over_credit = RNG.uniform(1.5, 3.0)
        sat_delta = float(RNG.uniform(-50, -20))
    elif r < 0.04:  # rare random anomaly anywhere (data-entry / fraud)
        archetype = "anomalous"
        spike = RNG.uniform(5, 12)
        over_credit = RNG.uniform(2.5, 5)

    total_issued = int(est_annual * years * over_credit)
    # Junk credits get dumped: retirement rates diverge from the market.
    retire_rate = RNG.beta(4, 3) if archetype == "clean" else RNG.beta(2, 4)
    total_retired = int(total_issued * retire_rate)

    pid = f"{REGISTRY_PREFIX[registry]}{1000 + i}"
    name = f"{RNG.choice(NAME_WORDS)} {RNG.choice(NAME_WORDS)} {ptype.split(' (')[0]} Project"
    return {
        "project_id": pid,
        "project_name": name,
        "registry": registry,
        "project_type": ptype,
        "methodology": RNG.choice(meths),
        "country": RNG.choice(countries),
        "first_vintage": first_vintage,
        "last_vintage": last_vintage,
        "est_annual_reductions": int(est_annual),
        "total_issued": total_issued,
        "total_retired": total_retired,
        "max_to_median_issuance": round(float(spike), 2),
        "buffer_pool_pct": round(buffer_pct, 1),
        "satellite_cover_delta_pct": None if np.isnan(sat_delta) else round(sat_delta, 1),
        "verifier_changes": verifier_changes,
        "has_corresponding_adjustment": bool(RNG.random() < 0.12),
        "_archetype": archetype,  # ground truth for evaluation only - never a model input
    }


def main(n=420):
    names = list(TYPES)
    shares = np.array([TYPES[t][3] for t in names])
    types = RNG.choice(names, size=n, p=shares / shares.sum())
    df = pd.DataFrame([make_project(i, t) for i, t in enumerate(types)])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"wrote {len(df)} projects -> {OUT}")
    print(df["_archetype"].value_counts().to_string())


if __name__ == "__main__":
    main()
