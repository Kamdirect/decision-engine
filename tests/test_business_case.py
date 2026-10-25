"""Tests for the business case: hand-checked cost arithmetic and the simulation's logic."""

import pandas as pd
import pytest

from src.business_case import (ASSUMPTIONS, annual_cost, break_even_scale, cost_per_gbp,
                               error_value, midpoint, simulate, summarise)


@pytest.fixture
def tiny():
    """Two forecasts for product 1 (price £10): one 20 cases too high, one 10 cases too low."""
    results = pd.DataFrame({"product_id": [1, 1], "volume_cases": [100, 100],
                            "xgboost": [120, 90], "growth_12m": [150, 50]})
    return results, pd.Series({1: 10.0})


def test_error_value_splits_over_and_under_forecasts(tiny):
    results, prices = tiny
    err = error_value(results, prices, "xgboost")
    assert err["over_gbp"].tolist() == [200.0, 0.0]
    assert err["under_gbp"].tolist() == [0.0, 100.0]


def test_cost_per_pound_by_hand():
    a = {"gross_margin": 0.30, "lost_share": 0.50, "holding_rate": 0.24, "write_off": 0.01}
    over, under = cost_per_gbp(a)
    assert over == pytest.approx(0.24 / 12 * 0.70 + 0.01)   # 0.024
    assert under == pytest.approx(0.15)
    assert under > over  # a lost sale costs more than a month of extra stock


def test_annual_cost_by_hand(tiny):
    results, prices = tiny
    a = {"gross_margin": 0.30, "lost_share": 0.50, "holding_rate": 0.24, "write_off": 0.01}
    assert annual_cost(error_value(results, prices, "xgboost"), a) == pytest.approx(200 * 0.024 + 100 * 0.15)


def test_a_perfect_forecast_saves_exactly_the_rules_error_cost(tiny):
    results, prices = tiny
    results = results.assign(xgboost=results["volume_cases"])
    sim = simulate(results, prices, {"all": pd.Series([True, True])}, n=200)
    over = sim["a_holding_rate"] / 12 * (1 - sim["a_gross_margin"]) + sim["a_write_off"]
    under = sim["a_gross_margin"] * sim["a_lost_share"]
    pd.testing.assert_series_equal(sim["saving_all"], 500 * over + 500 * under, check_names=False)


def test_draws_stay_inside_the_stated_ranges_and_are_reproducible(tiny):
    results, prices = tiny
    groups = {"all": pd.Series([True, True])}
    a, b = simulate(results, prices, groups, n=500), simulate(results, prices, groups, n=500)
    pd.testing.assert_frame_equal(a, b)
    for k, v in ASSUMPTIONS.items():
        assert a[f"a_{k}"].between(v.low, v.high).all()


def test_costs_are_charged_in_the_net_value(tiny):
    results, prices = tiny
    sim = simulate(results, prices, {"all": pd.Series([True, True])}, n=100, years=3)
    expected = 3 * sim["saving_all"] - sim["a_build_cost"] - 3 * sim["a_run_cost"]
    pd.testing.assert_series_equal(sim["net_3y_all"], expected, check_names=False)
    lhs = break_even_scale(sim, "all") * 3 * sim["saving_all"]
    assert lhs.tolist() == pytest.approx((sim["a_build_cost"] + 3 * sim["a_run_cost"]).tolist())


def test_summary_hides_the_raw_assumption_draws(tiny):
    results, prices = tiny
    table = summarise(simulate(results, prices, {"all": pd.Series([True, True])}, n=100))
    assert not any(i.startswith("a_") for i in table.index)
    assert midpoint()["gross_margin"] == pytest.approx(0.325)
