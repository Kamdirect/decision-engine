"""Business case for ML promotion forecasting, with every assumption stated as a range.

Uses the 2025 walk-forward forecasts (one year) on the committed data, values each
forecast error at list price, and samples the cost assumptions 10,000 times.

Run from the project root:  python -m scripts.business_case   (about 10 seconds, free)
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pandas as pd

from src.business_case import ASSUMPTIONS, break_even_scale, drivers, simulate, summarise
from src.forecast import load_panel, walk_forward

DB = Path("data/sales.db")
OUT = Path("docs/business_case.csv")
TEST_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]


def main() -> None:
    panel = load_panel(DB)
    results = walk_forward(panel, TEST_MONTHS)
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as con:
        prices = pd.read_sql("SELECT product_id, list_price_gbp FROM products", con) \
            .set_index("product_id")["list_price_gbp"]
    promoted = results["product_id"].isin(set(panel.loc[panel["discount_pct"] > 0, "product_id"]))
    groups = {"promoted": promoted, "never_promoted": ~promoted, "all": promoted | ~promoted}
    sim = simulate(results, prices, groups)
    revenue = float((results["volume_cases"] * results["product_id"].map(prices)).sum())

    pd.set_option("display.width", 140)
    print("Assumptions (each sampled uniformly between low and high):")
    for k, a in ASSUMPTIONS.items():
        print(f"  {k:<13} {a.low:>9,.2f} to {a.high:>9,.2f}  {a.unit}")
    table = summarise(sim)
    print("\nGBP. saving_* = yearly saving from XGBoost instead of 'last year x 12-month growth';")
    print("net_3y_* = 3 years of savings minus build cost and 3 years of running cost.")
    print((table.drop(columns="chance_below_zero").map(lambda v: f"{v:,.0f}")
           .join(table["chance_below_zero"].map(lambda v: f"{v:.0%}"))).to_string())
    print("\nWhat drives the 3-year value for promoted products (correlation with the result):")
    print(drivers(sim, "net_3y_promoted").to_string())
    scale = break_even_scale(sim, "promoted")
    print(f"\nBreak-even business size for promoted products, at list-price revenue "
          f"(this business: GBP {revenue / 1e6:.1f}m a year):")
    print(f"  median GBP {scale.median() * revenue / 1e6:.1f}m, 90% range "
          f"GBP {scale.quantile(0.05) * revenue / 1e6:.1f}m to {scale.quantile(0.95) * revenue / 1e6:.1f}m")
    OUT.parent.mkdir(exist_ok=True)
    table.to_csv(OUT)
    print(f"\nSaved {OUT}")


if __name__ == "__main__":
    main()
