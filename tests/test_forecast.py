"""Tests for the forecasting module: correctness of the baselines and metric, and no leakage."""

import numpy as np
import pandas as pd
import pytest

from src.forecast import load_panel, score, walk_forward, wmape


@pytest.fixture(scope="module")
def panel():
    return load_panel()


@pytest.fixture(scope="module")
def results(panel):
    return walk_forward(panel, ["2025-03", "2025-07"])


def test_wmape_on_a_hand_worked_example():
    # errors 10 and 30 on a total of 200 -> 20%
    assert wmape(pd.Series([100, 100]), pd.Series([90, 130])) == pytest.approx(20.0)


def test_seasonal_naive_is_last_years_value(panel, results):
    row = results.iloc[0]
    last_year = panel[(panel["product_id"] == row.product_id) & (panel["region_id"] == row.region_id)
                      & (panel["month"] == f"{int(row.month[:4]) - 1}{row.month[4:]}")]
    assert row.naive == last_year["volume_cases"].iloc[0]


def test_all_methods_scored_on_the_same_rows(results):
    assert results[["naive", "growth_3m", "growth_12m", "xgboost"]].notna().all().all()
    assert (results[["naive", "growth_3m", "growth_12m", "xgboost"]] > 0).all().all()


def test_no_leakage_from_the_future(panel):
    """Changing every sale from 2025-04 onwards must not change the forecast for 2025-03."""
    before = walk_forward(panel, ["2025-03"])
    tampered = panel.copy()
    future = tampered["period"] >= pd.Period("2025-04", "M")
    tampered.loc[future, "volume_cases"] = tampered.loc[future, "volume_cases"] * 5
    after = walk_forward(tampered, ["2025-03"])
    np.testing.assert_allclose(before["xgboost"], after["xgboost"])


def test_score_credits_ml_only_against_the_best_simple_rule(results):
    s = score(results).iloc[0]
    best_simple = min(s["naive_wmape"], s["growth_3m_wmape"], s["growth_12m_wmape"])
    assert s["ml_gain_pts"] == pytest.approx(round(best_simple - s["xgboost_wmape"], 1), abs=0.11)


def test_results_are_reproducible(panel):
    a = walk_forward(panel, ["2025-06"])
    b = walk_forward(panel, ["2025-06"])
    np.testing.assert_allclose(a["xgboost"], b["xgboost"])
