"""Independent check: re-run the whole forecast comparison on 10 datasets never used in development.

Why: the model design (predicting the ratio to last year) and the growth-adjusted baselines
were chosen while looking at 2025 results on the committed data (seed 7). So the committed
2025 results are no longer a fully untouched test. These 10 seeds (101-110) were never run
before this script was written. Same settings, same code, nothing tuned.

Run from the project root:  python -m scripts.independent_check   (about 40 seconds, free)
"""

from pathlib import Path

import pandas as pd

from src.forecast import panel_from_tables, score, series_wins, walk_forward
from src.synthetic_data import generate_tables

OUT = Path("docs/independent_check.csv")
SEEDS = range(101, 111)
TEST_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]


def segment(on_promotion: int, product_id: int, promoted: set) -> str:
    if on_promotion:
        return "promotion months"
    return "promoted SKUs, normal months" if product_id in promoted else "never-promoted SKUs"


def main() -> None:
    rows, wins = [], []
    for seed in SEEDS:
        t = generate_tables(seed)
        res = walk_forward(panel_from_tables(t["sales"], t["products"], t["promotions"]), TEST_MONTHS)
        promoted = set(t["promotions"]["product_id"])
        res["segment"] = [segment(o, p, promoted) for o, p in zip(res["on_promotion"], res["product_id"])]
        for df in (score(res).assign(segment="ALL"), score(res, "segment")):
            rows.append(df.assign(seed=seed))
        w = series_wins(res)
        w["promoted"] = w["product_id"].isin(promoted)
        wins.append(w.assign(seed=seed))
        print(f"  seed {seed} done")

    out = pd.concat(rows)
    g = out.groupby("segment", sort=False)["ml_gain_pts"]
    summary = pd.DataFrame({
        "mean_gain_pts": g.mean().round(1), "min_gain_pts": g.min().round(1),
        "max_gain_pts": g.max().round(1),
        "seeds_ml_better": g.apply(lambda s: f"{(s > 0).sum()} of {len(s)}"),
        "xgboost_wmape": out.groupby("segment", sort=False)["xgboost_wmape"].mean().round(1),
        "best_rule_wmape": out.assign(b=out[[c for c in out if c.endswith("_wmape") and c != "xgboost_wmape"]]
                                      .min(axis=1)).groupby("segment", sort=False)["b"].mean().round(1),
    })
    w = pd.concat(wins)
    series = w.groupby("promoted").agg(series=("ml_wins", "size"),
                                       ml_wins_pct=("ml_wins", lambda s: round(100 * s.mean(), 1)),
                                       median_gain_pts=("gain_pts", lambda s: round(s.median(), 1)))
    series.index = series.index.map({True: "promoted SKUs", False: "never-promoted SKUs"})

    pd.set_option("display.width", 140)
    print("\nML gain vs the best simple rule, 10 unseen datasets (WMAPE points; positive = ML better)")
    print(summary.to_string())
    print("\nPer series: does XGBoost beat 'last year x 12-month growth' over the year?")
    print(series.to_string())
    OUT.parent.mkdir(exist_ok=True)
    summary.to_csv(OUT)
    series.to_csv(OUT.with_name("independent_check_series.csv"))
    print(f"\nSaved {OUT} and {OUT.with_name('independent_check_series.csv')}")


if __name__ == "__main__":
    main()
