"""Build a synthetic FMCG sales database for a fictional drinks company.

The shape mirrors a real distributor dataset (30 SKUs, 3 regions, 36 months, summer peaks,
double-digit growth), but every number is generated here from a fixed seed. No real
company data is used.

Known structure is planted on purpose, so later steps can be tested against it:
  - planned promotions on 12 of the 30 SKUs (volume uplift, price discount, a small
    post-promotion dip the following month),
  - 3 product launches in 2024-01 with a ramp-up,
  - 1 product delisted after 2025-06,
  - a supply disruption: carbonated drinks in the South, 2024-07, volume -35%.

Run from the project root:  python -m src.synthetic_data
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 7
COMPANY = "Meridian Drinks Co. (fictional)"
MONTHS = pd.period_range("2023-01", "2025-12", freq="M")
DB_PATH = Path("data/sales.db")

REGIONS = [
    {"region_id": 1, "region_name": "North", "scale": 1.00},
    {"region_id": 2, "region_name": "Central", "scale": 1.35},
    {"region_id": 3, "region_name": "South", "scale": 0.80},
]

# category -> (seasonal amplitude, typical case price in GBP)
CATEGORIES = {
    "Carbonated": (0.35, 9.0),
    "Water": (0.40, 4.5),
    "Juice": (0.15, 13.0),
    "Energy": (0.10, 18.0),
}

PRODUCT_NAMES = {
    "Carbonated": ["Cola 330ml", "Cola 500ml", "Cola 1.5L", "Diet Cola 330ml", "Diet Cola 500ml",
                   "Lemon Lime 330ml", "Lemon Lime 1.5L", "Orange Fizz 330ml", "Orange Fizz 1.5L",
                   "Ginger Ale 330ml", "Cream Soda 500ml", "Cherry Cola 330ml"],
    "Water": ["Still Water 500ml", "Still Water 1.5L", "Sparkling Water 500ml",
              "Sparkling Water 1L", "Flavoured Water 500ml", "Still Water 5L"],
    "Juice": ["Orange Juice 1L", "Apple Juice 1L", "Mango Juice 1L", "Mixed Fruit 250ml",
              "Orange Juice 250ml", "Pineapple Juice 1L"],
    "Energy": ["Energy Original 250ml", "Energy Sugar Free 250ml", "Energy Tropical 250ml",
               "Energy Original 500ml", "Sports Citrus 500ml", "Sports Berry 500ml"],
}

PROMOTED = 12                      # how many SKUs ever get promotions
LAUNCH_MONTH = pd.Period("2024-01", "M")
DELIST_AFTER = pd.Period("2025-06", "M")
DISRUPTION = {"month": pd.Period("2024-07", "M"), "region_id": 3, "category": "Carbonated", "factor": 0.65}


def on_sale(product, month: pd.Period) -> bool:
    """True if the product is listed in this month (launched, and not yet delisted)."""
    if month < pd.Period(product.launch_month, "M"):
        return False
    return not (isinstance(product.delist_after, str) and month > pd.Period(product.delist_after, "M"))


def build_products(rng: np.random.Generator) -> pd.DataFrame:
    rows, pid = [], 1
    for category, names in PRODUCT_NAMES.items():
        _, price = CATEGORIES[category]
        for name in names:
            rows.append(
                {
                    "product_id": pid,
                    "product_name": name,
                    "category": category,
                    "list_price_gbp": round(price * rng.uniform(0.8, 1.25), 2),
                    "base_cases": int(rng.uniform(300, 1500)),
                    "annual_growth": round(rng.uniform(0.06, 0.20), 3),
                }
            )
            pid += 1
    products = pd.DataFrame(rows)

    ids = products["product_id"].to_numpy()
    shuffled = rng.permutation(ids)
    launched = set(shuffled[:3])
    delisted = {shuffled[3]}
    promoted = set(shuffled[4 : 4 + PROMOTED])
    products["launch_month"] = [str(LAUNCH_MONTH) if p in launched else str(MONTHS[0]) for p in ids]
    products["delist_after"] = [str(DELIST_AFTER) if p in delisted else None for p in ids]
    products["is_promoted"] = [int(p in promoted) for p in ids]
    return products


def build_promotions(products: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Planned promotions: about 1 month in 6 for each promoted SKU-region, never back to back."""
    rows = []
    for p in products[products["is_promoted"] == 1].itertuples():
        for r in REGIONS:
            last = -10
            for t, month in enumerate(MONTHS):
                if not on_sale(p, month):
                    continue
                if t - last >= 3 and rng.random() < 0.18:
                    rows.append(
                        {
                            "month": str(month),
                            "region_id": r["region_id"],
                            "product_id": p.product_id,
                            "discount_pct": int(rng.choice([10, 15, 20])),
                            "planned_uplift": round(float(rng.uniform(1.25, 1.6)), 2),
                        }
                    )
                    last = t
    return pd.DataFrame(rows)


def build_sales(products: pd.DataFrame, promotions: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    promo = {(r.month, r.region_id, r.product_id): r for r in promotions.itertuples()}
    rows = []
    for p in products.itertuples():
        amplitude, _ = CATEGORIES[p.category]
        launch = pd.Period(p.launch_month, "M")
        for r in REGIONS:
            for t, month in enumerate(MONTHS):
                m = str(month)
                if not on_sale(p, month):
                    continue
                season = 1 + amplitude * np.sin((month.month - 4) / 12 * 2 * np.pi)
                growth = (1 + p.annual_growth) ** (t / 12)
                ramp = min(1.0, 0.35 + 0.65 * (month - launch).n / 6) if launch > MONTHS[0] else 1.0
                volume = p.base_cases * r["scale"] * season * growth * ramp

                key = (m, r["region_id"], p.product_id)
                discount = 0
                if key in promo:
                    volume *= promo[key].planned_uplift
                    discount = promo[key].discount_pct
                elif (str(month - 1), r["region_id"], p.product_id) in promo:
                    volume *= 0.92  # customers stocked up during last month's promotion
                if (month == DISRUPTION["month"] and r["region_id"] == DISRUPTION["region_id"]
                        and p.category == DISRUPTION["category"]):
                    volume *= DISRUPTION["factor"]

                volume = max(0, int(round(volume * rng.lognormal(0, 0.06))))
                price = p.list_price_gbp * (1 - discount / 100) * rng.normal(1, 0.01)
                rows.append(
                    {
                        "month": m,
                        "region_id": r["region_id"],
                        "product_id": p.product_id,
                        "volume_cases": volume,
                        "revenue_gbp": round(volume * price, 2),
                        "on_promotion": int(discount > 0),
                    }
                )
    return pd.DataFrame(rows)


SCHEMA = """
CREATE TABLE regions (
    region_id   INTEGER PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE
);
CREATE TABLE products (
    product_id     INTEGER PRIMARY KEY,
    product_name   TEXT NOT NULL UNIQUE,
    category       TEXT NOT NULL,
    list_price_gbp REAL NOT NULL CHECK (list_price_gbp > 0),
    launch_month   TEXT NOT NULL,
    delist_after   TEXT
);
CREATE TABLE promotions (
    month          TEXT NOT NULL,
    region_id      INTEGER NOT NULL REFERENCES regions(region_id),
    product_id     INTEGER NOT NULL REFERENCES products(product_id),
    discount_pct   INTEGER NOT NULL CHECK (discount_pct BETWEEN 0 AND 100),
    planned_uplift REAL NOT NULL,
    PRIMARY KEY (month, region_id, product_id)
);
CREATE TABLE sales (
    month        TEXT NOT NULL,
    region_id    INTEGER NOT NULL REFERENCES regions(region_id),
    product_id   INTEGER NOT NULL REFERENCES products(product_id),
    volume_cases INTEGER NOT NULL CHECK (volume_cases >= 0),
    revenue_gbp  REAL NOT NULL CHECK (revenue_gbp >= 0),
    on_promotion INTEGER NOT NULL CHECK (on_promotion IN (0, 1)),
    PRIMARY KEY (month, region_id, product_id)
);
"""


def build_database(path: Path = DB_PATH, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    products = build_products(rng)
    promotions = build_promotions(products, rng)
    sales = build_sales(products, promotions, rng)
    regions = pd.DataFrame(REGIONS)[["region_id", "region_name"]]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with closing(sqlite3.connect(path)) as con, con:
        con.executescript(SCHEMA)
        regions.to_sql("regions", con, if_exists="append", index=False)
        products[["product_id", "product_name", "category", "list_price_gbp", "launch_month",
                  "delist_after"]].to_sql("products", con, if_exists="append", index=False)
        promotions.to_sql("promotions", con, if_exists="append", index=False)
        sales.to_sql("sales", con, if_exists="append", index=False)
    return {"regions": len(regions), "products": len(products),
            "promotions": len(promotions), "sales": len(sales)}


def main() -> None:
    counts = build_database()
    print(f"{COMPANY}: database written to {DB_PATH}")
    for table, n in counts.items():
        print(f"  {table:<11} {n:>6} rows")


if __name__ == "__main__":
    main()
