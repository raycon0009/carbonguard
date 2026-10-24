"""Shared helpers for the AI tests: run the whole pipeline into a temp folder."""
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

AI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AI))
import generate_data as gd  # noqa: E402
import train_and_score as ts  # noqa: E402

DEFAULT_SEED = 2026


def sha256(path):
    return "0x" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_pipeline(out_dir, seed=DEFAULT_SEED):
    """Generate data and train/score into out_dir, never touching the repo files."""
    out_dir = Path(out_dir)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gd, "RNG", np.random.default_rng(seed))
        mp.setattr(gd, "OUT", out_dir / "data" / "projects_raw.csv")
        mp.setattr(ts, "RAW", out_dir / "data" / "projects_raw.csv")
        mp.setattr(ts, "SCORED", out_dir / "data" / "projects_scored.csv")
        mp.setattr(ts, "MODEL", out_dir / "model" / "carbonguard_risk_v1.joblib")
        mp.setattr(ts, "META", out_dir / "model" / "model_meta.json")
        mp.setattr(ts, "CHARTS", out_dir / "charts")
        mp.setattr(ts, "WEB_MODEL", out_dir / "web" / "sandbox_model.js")
        gd.main()
        ts.main()
    return {
        "raw": pd.read_csv(out_dir / "data" / "projects_raw.csv"),
        "scored": pd.read_csv(out_dir / "data" / "projects_scored.csv"),
        "meta": json.loads((out_dir / "model" / "model_meta.json").read_text()),
        "bundle": joblib.load(out_dir / "model" / "carbonguard_risk_v1.joblib"),
        "dir": out_dir,
    }
