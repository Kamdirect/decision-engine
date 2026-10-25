"""What are better promotion forecasts worth? A transparent, assumption-driven business case.

The decision: should the company build and run an ML forecast, and for which products?

How a forecast error turns into money (one month, one product, one region):
  - Stock is ordered to the forecast.
  - Forecast too HIGH: excess cases sit in the warehouse for a month. They are not thrown
    away (drinks keep for months), so the cost is holding cost plus a small write-off share.
  - Forecast too LOW: some shoppers buy another of our products or wait; the rest buy a
    competitor's. The lost share of the shortfall costs its gross margin.
So an under-forecast case costs several times more than an over-forecast case.

Every number below that is not computed from the data is an ASSUMPTION, given as a range
with its reasoning. The ranges are sampled together (Monte Carlo) so the result is a range,
not a single number. Nothing here is a measured saving: the data is synthetic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Assumption:
    low: float
    high: float
    unit: str
    why: str


ASSUMPTIONS = {
    "gross_margin": Assumption(
        0.25, 0.40, "share of list price",
        "Typical gross margin range for branded soft drinks at distributor level."),
    "lost_share": Assumption(
        0.30, 0.70, "share of a shortfall",
        "Share of unmet demand that is lost rather than substituted within our range or "
        "delayed. Wide on purpose: substitution varies by brand strength."),
    "holding_rate": Assumption(
        0.15, 0.30, "per year, share of stock cost",
        "Annual inventory holding cost (capital, warehousing, handling); 15-30% is the "
        "common textbook range."),
    "write_off": Assumption(
        0.00, 0.05, "share of an excess case",
        "Share of excess stock eventually discounted or written off (short-dated stock)."),
    "build_cost": Assumption(
        20_000, 60_000, "GBP, one-off",
        "Building, validating and integrating the model into ordering: roughly 2-6 months "
        "of one analyst's time."),
    "run_cost": Assumption(
        10_000, 30_000, "GBP per year",
        "Monitoring, monthly retraining, fixing data feeds and explaining forecasts to planners."),
}


def error_value(results: pd.DataFrame, prices: pd.Series, method: str) -> pd.DataFrame:
    """Excess and shortfall, in GBP at list price, for one method. One row per forecast."""
    price = results["product_id"].map(prices)
    gap = results[method] - results["volume_cases"]
    return pd.DataFrame({"over_gbp": gap.clip(lower=0) * price,
                         "under_gbp": (-gap).clip(lower=0) * price})


def cost_per_gbp(a: dict) -> tuple[float, float]:
    """Cost of £1 of over-forecast and of £1 of under-forecast, given one set of assumptions."""
    over = a["holding_rate"] / 12 * (1 - a["gross_margin"]) + a["write_off"]
    under = a["gross_margin"] * a["lost_share"]
    return over, under


def annual_cost(err: pd.DataFrame, a: dict) -> float:
    over, under = cost_per_gbp(a)
    return float(err["over_gbp"].sum() * over + err["under_gbp"].sum() * under)


def midpoint() -> dict:
    return {k: (v.low + v.high) / 2 for k, v in ASSUMPTIONS.items()}


def simulate(results: pd.DataFrame, prices: pd.Series, groups: dict[str, pd.Series],
             rule: str = "growth_12m", n: int = 10_000, seed: int = 0,
             years: int = 3) -> pd.DataFrame:
    """Sample every assumption uniformly within its range, n times. For each draw and each group
    of products: the yearly saving from XGBoost instead of the rule, and the net value over
    `years` years after build and running costs. Costs are charged once, to the whole system."""
    rng = np.random.default_rng(seed)
    ml, base = error_value(results, prices, "xgboost"), error_value(results, prices, rule)
    sums = {name: {"ml_over": ml.loc[m, "over_gbp"].sum(), "ml_under": ml.loc[m, "under_gbp"].sum(),
                   "rule_over": base.loc[m, "over_gbp"].sum(),
                   "rule_under": base.loc[m, "under_gbp"].sum()}
            for name, m in groups.items()}
    draws = {k: rng.uniform(v.low, v.high, n) for k, v in ASSUMPTIONS.items()}
    over = draws["holding_rate"] / 12 * (1 - draws["gross_margin"]) + draws["write_off"]
    under = draws["gross_margin"] * draws["lost_share"]
    out = {}
    for name, s in sums.items():
        rule_cost = s["rule_over"] * over + s["rule_under"] * under
        ml_cost = s["ml_over"] * over + s["ml_under"] * under
        out[f"saving_{name}"] = rule_cost - ml_cost
    df = pd.DataFrame(out)
    for k, v in draws.items():
        df[f"a_{k}"] = v
    for name in groups:
        df[f"net_{years}y_{name}"] = (years * df[f"saving_{name}"] - draws["build_cost"]
                                      - years * draws["run_cost"])
    return df


def drivers(sim: pd.DataFrame, target: str) -> pd.Series:
    """Which assumption moves the result most: correlation of each assumption with `target`
    across the draws (a simple tornado chart in numbers)."""
    cols = [c for c in sim if c.startswith("a_")]
    corr = sim[cols].corrwith(sim[target]).rename(lambda c: c[2:])
    return corr.reindex(corr.abs().sort_values(ascending=False).index).round(2)


def break_even_scale(sim: pd.DataFrame, name: str, years: int = 3) -> pd.Series:
    """How many times bigger (in volume) the business must be for the model to break even over
    `years` years, per draw. Savings grow with volume; build and running costs mostly don't."""
    return (sim["a_build_cost"] + years * sim["a_run_cost"]) / (years * sim[f"saving_{name}"])


def summarise(sim: pd.DataFrame) -> pd.DataFrame:
    """Median and 90% range of every column, plus the chance that it is below zero."""
    sim = sim[[c for c in sim if not c.startswith("a_")]]
    return pd.DataFrame({
        "p5": sim.quantile(0.05), "median": sim.median(), "p95": sim.quantile(0.95),
        "chance_below_zero": (sim < 0).mean(),
    }).round(3)
