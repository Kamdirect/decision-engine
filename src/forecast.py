"""Forecasting: two simple baselines vs a global XGBoost model, judged by walk-forward validation.

Design choices (each one matters, and each is a question an interviewer may ask):
  - Seasonal naive = same month last year. The classic bar any model must clear.
  - Last-month naive = last month's actual. A non-seasonal baseline: it shows how much of the
    problem is seasonality (on strongly seasonal drinks it should do badly).
  - Two growth-adjusted naives = same month last year x recent growth (last 3 or last 12 months
    versus the same months a year earlier). Plain seasonal naive ignores growth, so on growing
    series it is biased low and too easy to beat. ML is only credited with beating the BEST of
    the three simple rules.
  - XGBoost predicts the RATIO to the same month last year (log scale), not the raw volume.
    Trees cannot extrapolate beyond the values they were trained on, so on growing series a
    raw-volume model under-forecasts; a ratio model inherits the level from last year and
    only has to learn what changes (growth, promotions, launches).
  - One GLOBAL model across all SKU x region series. With 36 months per series, a model per
    series would have about 24 training points: far too few.
  - Walk-forward: to forecast month m, train only on months before m. Never on the future.
  - "Best rule" in score() is picked per segment AFTER seeing the results. That favours the
    simple rules, so ML gains reported against it are conservative.
  - Planned promotions are known in advance (they are in the promotions calendar), so using
    them as a feature is legitimate. Actual sales of the month being forecast are not.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

DB_PATH = Path("data/sales.db")
SIMPLE = ["last_month", "naive", "growth_3m", "growth_12m"]
METHODS = SIMPLE + ["xgboost"]
FEATURES = ["month_of_year", "on_promotion", "discount_pct", "promo_last_month",
            "months_since_launch", "lag_1_ratio", "lag_2_ratio", "yoy_trend", "category_code",
            "region_id"]
# Fixed, modest settings: not tuned on the test months (tuning on them would leak).
XGB_PARAMS = {"max_depth": 3, "eta": 0.05, "subsample": 0.8, "colsample_bytree": 0.8,
              "objective": "reg:squarederror", "nthread": 1}


def panel_from_tables(sales: pd.DataFrame, products: pd.DataFrame,
                      promotions: pd.DataFrame) -> pd.DataFrame:
    """One row per month x region x SKU, with the planned promotion calendar joined on."""
    df = (
        sales[["month", "region_id", "product_id", "volume_cases"]]
        .merge(products[["product_id", "category", "launch_month"]], on="product_id")
        .merge(promotions[["month", "region_id", "product_id", "discount_pct"]],
               on=["month", "region_id", "product_id"], how="left")
    )
    df["discount_pct"] = df["discount_pct"].fillna(0)
    df["period"] = pd.PeriodIndex(df["month"], freq="M")
    return df.sort_values(["product_id", "region_id", "period"]).reset_index(drop=True)


def load_panel(db_path: Path = DB_PATH) -> pd.DataFrame:
    """Read the database (read-only) and build the panel."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        tables = {t: pd.read_sql(f"SELECT * FROM {t}", con)
                  for t in ["sales", "products", "promotions"]}
    return panel_from_tables(tables["sales"], tables["products"], tables["promotions"])


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Features use only information available before the month being forecast,
    except the promotion calendar, which is planned in advance."""
    out = df.copy()
    by_period = out.set_index(["product_id", "region_id", "period"])

    def lag(column: str, k: int) -> np.ndarray:
        keys = list(zip(out["product_id"], out["region_id"], out["period"] - k))
        return by_period[column].reindex(keys).to_numpy()

    lags = {k: lag("volume_cases", k) for k in range(1, 25)}
    for k in (1, 2, 3, 12, 13, 14, 15, 24):
        out[f"lag_{k}"] = lags[k]
    # How recent months compare with the same months a year earlier: captures growth.
    out["lag_1_ratio"] = np.log(out["lag_1"] / out["lag_13"])
    out["lag_2_ratio"] = np.log(out["lag_2"] / out["lag_14"])
    out["yoy_trend"] = np.log(out["lag_12"] / out["lag_24"])
    with np.errstate(divide="ignore", invalid="ignore"):
        out["g3"] = sum(lags[k] for k in (1, 2, 3)) / sum(lags[k] for k in (13, 14, 15))
        out["g12"] = sum(lags[k] for k in range(1, 13)) / sum(lags[k] for k in range(13, 25))
    out["month_of_year"] = out["period"].dt.month
    out["on_promotion"] = (out["discount_pct"] > 0).astype(int)
    out["promo_last_month"] = np.nan_to_num(lag("discount_pct", 1)) > 0
    out["promo_last_month"] = out["promo_last_month"].astype(int)
    out["months_since_launch"] = (
        out["period"] - pd.PeriodIndex(out["launch_month"], freq="M")
    ).apply(lambda d: d.n)
    out["category_code"] = out["category"].astype("category").cat.codes
    with np.errstate(divide="ignore", invalid="ignore"):
        out["target"] = np.log(out["volume_cases"] / out["lag_12"])
    return out


def walk_forward(panel: pd.DataFrame, test_months: list[str], seed: int = 0) -> pd.DataFrame:
    """For each test month, train on everything before it and forecast that month with all
    three methods. Rows without a value 12 months earlier cannot be forecast by any method
    and are skipped, so all methods are scored on exactly the same rows."""
    data = add_features(panel)
    results = []
    for month in test_months:
        m = pd.Period(month, "M")
        train = data[(data["period"] < m) & np.isfinite(data["target"])]
        test = data[(data["period"] == m) & (data["lag_12"] > 0)]
        if test.empty:
            continue
        model = xgb.train(
            XGB_PARAMS | {"seed": seed},
            xgb.DMatrix(train[FEATURES], label=train["target"]),
            num_boost_round=300,
        )
        pred_ratio = np.exp(model.predict(xgb.DMatrix(test[FEATURES])))
        # Where a growth rate cannot be computed (e.g. recent launches), assume no growth.
        g3 = test["g3"].where(np.isfinite(test["g3"]), 1.0)
        g12 = test["g12"].where(np.isfinite(test["g12"]), 1.0)
        results.append(
            test[["month", "region_id", "product_id", "category", "on_promotion",
                  "volume_cases"]].assign(
                last_month=test["lag_1"].where(test["lag_1"] > 0, test["lag_12"]),
                naive=test["lag_12"],
                growth_3m=test["lag_12"] * g3,
                growth_12m=test["lag_12"] * g12,
                xgboost=test["lag_12"] * pred_ratio,
            )
        )
    return pd.concat(results, ignore_index=True)


def wmape(actual: pd.Series, forecast: pd.Series) -> float:
    """Weighted MAPE: total absolute error as a % of total actual volume. Unlike plain MAPE,
    small products cannot dominate it, and it is not undefined when a month has zero sales."""
    return float(100 * (actual - forecast).abs().sum() / actual.sum())


def mae(actual: pd.Series, forecast: pd.Series) -> float:
    """Mean absolute error, in cases per product-region-month. Easier to turn into stock and
    money than a percentage, but larger products weigh more."""
    return float((actual - forecast).abs().mean())


METRICS = {"wmape": wmape, "mae": mae}


def score(results: pd.DataFrame, by: str | None = None, metric: str = "wmape") -> pd.DataFrame:
    """Error of each method, overall or per group. 'ml_gain' compares XGBoost with the best
    of the simple rules, so the ML only gets credit for beating the best rule. Positive = ML better.
    For WMAPE the gain is in percentage points (ml_gain_pts); for MAE, in cases (ml_gain_cases)."""
    fn = METRICS[metric]
    gain_name = "ml_gain_pts" if metric == "wmape" else "ml_gain_cases"
    groups = [("all", results)] if by is None else list(results.groupby(by))
    rows = []
    for name, g in groups:
        e = {m: fn(g["volume_cases"], g[m]) for m in METHODS}
        best_simple = min(e[m] for m in SIMPLE)
        rows.append({"segment": name, "rows": len(g)}
                    | {f"{m}_{metric}": round(v, 1) for m, v in e.items()}
                    | {"best_rule": min(SIMPLE, key=e.get),
                       gain_name: round(best_simple - e["xgboost"], 1)})
    return pd.DataFrame(rows)


def series_wins(results: pd.DataFrame, rule: str = "growth_12m") -> pd.DataFrame:
    """One row per product-region series: does XGBoost beat one fixed simple rule over the year?
    An average can hide a model that wins big on a few series and loses on many. The rule is
    fixed in advance (not the best rule per series, which would be chosen with hindsight)."""
    rows = []
    for (pid, rid), g in results.groupby(["product_id", "region_id"]):
        rule_err, ml_err = wmape(g["volume_cases"], g[rule]), wmape(g["volume_cases"], g["xgboost"])
        rows.append({"product_id": pid, "region_id": rid, "rule_wmape": rule_err,
                     "xgboost_wmape": ml_err, "gain_pts": rule_err - ml_err, "ml_wins": ml_err < rule_err})
    return pd.DataFrame(rows)
