"""Tests for the synthetic database: structure, integrity and the planted patterns."""

import sqlite3
from contextlib import closing

import pandas as pd
import pytest

from src.synthetic_data import build_database


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("data") / "sales.db"
    counts = build_database(path)
    with closing(sqlite3.connect(path)) as con:
        yield counts, (lambda sql: pd.read_sql(sql, con)), path


def test_row_counts(db):
    counts, _, _ = db
    # 30 SKUs x 3 regions x 36 months, minus 3 launches x 3 regions x 12 months,
    # minus 1 delisted SKU x 3 regions x 6 months
    assert counts == {"regions": 3, "products": 30, "promotions": counts["promotions"],
                      "sales": 30 * 3 * 36 - 3 * 3 * 12 - 3 * 6}
    assert 100 < counts["promotions"] < 300


def test_every_sale_points_to_a_real_product_and_region(db):
    _, q, _ = db
    orphans = q("""SELECT COUNT(*) n FROM sales s
                   LEFT JOIN products p USING (product_id)
                   LEFT JOIN regions r USING (region_id)
                   WHERE p.product_id IS NULL OR r.region_id IS NULL""")
    assert orphans.n[0] == 0


def test_no_sales_before_launch_or_after_delisting(db):
    _, q, _ = db
    bad = q("""SELECT COUNT(*) n FROM sales s JOIN products p USING (product_id)
               WHERE s.month < p.launch_month
                  OR (p.delist_after IS NOT NULL AND s.month > p.delist_after)""")
    assert bad.n[0] == 0


def test_promotion_flag_matches_promotion_calendar(db):
    _, q, _ = db
    mismatch = q("""SELECT COUNT(*) n FROM sales s
                    LEFT JOIN promotions pr USING (month, region_id, product_id)
                    WHERE (s.on_promotion = 1) <> (pr.month IS NOT NULL)""")
    assert mismatch.n[0] == 0


def test_promotions_lift_volume(db):
    _, q, _ = db
    lift = q("""SELECT AVG(CASE WHEN on_promotion = 1 THEN volume_cases END) * 1.0
                     / AVG(CASE WHEN on_promotion = 0 THEN volume_cases END) AS ratio
                FROM sales WHERE product_id IN (SELECT DISTINCT product_id FROM promotions)""")
    assert lift.ratio[0] > 1.2


def test_summer_peak_and_growth(db):
    _, q, _ = db
    by_month = q("""SELECT CAST(substr(month, 6, 2) AS INT) m, SUM(volume_cases) v
                    FROM sales GROUP BY m ORDER BY m""").set_index("m").v
    assert by_month.idxmax() in (6, 7, 8) and by_month.idxmin() in (12, 1, 2)
    by_year = q("SELECT substr(month, 1, 4) y, SUM(volume_cases) v FROM sales GROUP BY y").v
    assert by_year.is_monotonic_increasing


def test_supply_disruption_is_visible(db):
    _, q, _ = db
    v = q("""SELECT month, SUM(volume_cases) v FROM sales JOIN products USING (product_id)
             WHERE category = 'Carbonated' AND region_id = 3
               AND month IN ('2024-06', '2024-07', '2024-08') GROUP BY month""").set_index("month").v
    assert v["2024-07"] < 0.8 * min(v["2024-06"], v["2024-08"])


def test_build_is_reproducible(db, tmp_path):
    _, _, first = db
    second = tmp_path / "again.db"
    build_database(second)
    with closing(sqlite3.connect(first)) as a, closing(sqlite3.connect(second)) as b:
        for table in ["products", "promotions", "sales"]:
            pd.testing.assert_frame_equal(pd.read_sql(f"SELECT * FROM {table}", a),
                                          pd.read_sql(f"SELECT * FROM {table}", b))
