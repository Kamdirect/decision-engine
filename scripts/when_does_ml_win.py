"""When is ML worth it? Rerun the same walk-forward comparison on datasets that are
progressively messier (more noise, less stable growth and seasonality).

The committed database is the "clean" end of this range. Real FMCG data sits somewhere in it,
and where exactly is the question that decides whether ML is worth paying for.

Run from the project root:  python -m scripts.when_does_ml_win
"""

from pathlib import Path

import pandas as pd

from src.forecast import panel_from_tables, score, walk_forward
from src.synthetic_data import generate_tables

OUT = Path("docs/when_does_ml_win.csv")
TEST_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]
SEEDS = [7, 8, 9]
SCENARIOS = [
    # name,                                noise, growth_sd, season_sd, hetero
    ("clean (committed data)",             0.06,  0.00,      0.00,      0.0),
    ("noisier",                            0.12,  0.00,      0.00,      0.0),
    ("noisy + unstable",                   0.12,  0.08,      0.25,      0.0),
    ("very noisy + unstable",              0.20,  0.08,      0.25,      0.0),
    ("noisy + unstable + series differ",   0.12,  0.08,      0.25,      1.0),
    ("very noisy, unstable, series differ", 0.20,  0.08,      0.25,      1.0),
]


def segment(row) -> str:
    if row.on_promotion:
        return "promotion months"
    return "promoted SKUs, normal months" if row.ever_promoted else "never-promoted SKUs"


def main() -> None:
    rows = []
    for name, noise, growth_sd, season_sd, hetero in SCENARIOS:
        for seed in SEEDS:
            t = generate_tables(seed, noise, growth_sd, season_sd, hetero)
            res = walk_forward(panel_from_tables(t["sales"], t["products"], t["promotions"]),
                               TEST_MONTHS)
            promoted = set(t["promotions"]["product_id"])
            res["ever_promoted"] = res["product_id"].isin(promoted)
            res["segment"] = res.apply(segment, axis=1)
            for df in (score(res).assign(segment="ALL"), score(res, "segment")):
                rows.append(df.assign(scenario=name, seed=seed))
    out = pd.concat(rows)
    summary = (out.groupby(["scenario", "segment"], sort=False)
               [["last_month_wmape", "naive_wmape", "growth_3m_wmape", "growth_12m_wmape", "xgboost_wmape",
                "ml_gain_pts"]]
               .mean().round(1))
    pd.set_option("display.width", 140)
    print("Mean WMAPE (%) over seeds", SEEDS, "- walk-forward, 12 one-month-ahead forecasts")
    print("ml_gain_pts = best simple baseline minus XGBoost (positive = ML better)\n")
    print(summary.to_string())
    summary.to_csv(OUT)
    print(f"\nSaved to {OUT}")


if __name__ == "__main__":
    main()
