# Forecast evaluation

**Question:** does a machine-learning forecast beat simple rules enough to be worth using,
and if so, for which products?

**Answer:** yes for promoted products, and no for products that are never promoted. For a
never-promoted product, XGBoost beats the best simple rule on only about 6 products in 10,
by about half a point. A simple rule is the better choice there: free, transparent and
nearly as accurate.

All data is synthetic (see [data_dictionary.md](data_dictionary.md)). Every number below is
produced by code in this repository.

## 1. What each forecast is allowed to know

A forecast for month *m* is made at the end of month *m − 1*. Each input must be known by then.

| Input | Available at forecast time? | Why |
|---|---|---|
| Sales up to month *m − 1* (lags 1–3, 12–15, 24) | Yes | Already happened |
| Growth ratios built from those lags | Yes | Built only from past months |
| Planned promotion calendar for month *m* (on promotion, discount %) | Yes | Promotions are planned and agreed with retailers in advance |
| Promotion in month *m − 1* (post-promotion dip) | Yes | Already happened |
| Months since launch, category, region, calendar month | Yes | Fixed facts |
| **Actual sales in month *m*** | **No** | This is the target. It is never an input |

**Leakage test** (`tests/test_forecast.py`): multiplying every sale from 2025-04 onwards by 5
must not change the forecast for 2025-03. It doesn't, and the test was checked by
deliberately breaking it.

**Assumption to flag:** using the promotion calendar assumes promotions are planned at least
a month ahead and then executed as planned. If promotions are often added at short notice,
the ML advantage in promotion months will be smaller than shown here.

## 2. Procedure: what was used to develop, and what to test

| Stage | Data | What happened |
|---|---|---|
| Development | Committed dataset (seed 7), forecasts for 2025 | The method was built and inspected here. **Two design choices were made after seeing 2025 results:** XGBoost predicts the ratio to last year, because tree models cannot extrapolate growth; and growth-adjusted rules were added as baselines, because plain "same month last year" was too easy to beat. The second change made the test **harder** for ML, not easier |
| Fixed settings | n/a | XGBoost settings (depth 3, learning rate 0.05, 300 rounds) were fixed in advance and never tuned. The features were chosen from domain knowledge, not by searching |
| Stress test | 6 messier data scenarios × seeds 7–9 | Robustness to noise and unstable seasonality |
| **Independent check** | **Seeds 101–110, never run before the check script was written** | Same code, same settings, run once. Because seed 7's 2025 is no longer untouched, **this is the clean test** |

**Validation scheme:** walk-forward. To forecast each month of 2025, the model is retrained
on all months before it, giving 12 one-month-ahead forecasts per product-region series.
2023 is used only to build the year-ago inputs.

## 3. Baselines and metrics

| Method | Forecast for month *m* |
|---|---|
| Last month | Actual sales in *m − 1*: a non-seasonal baseline |
| Same month last year | Actual sales in *m − 12*: seasonal naive |
| Last year × 3-month growth | *m − 12*, scaled by the last 3 months against the same 3 months a year before |
| Last year × 12-month growth | *m − 12*, scaled by the last 12 months against the 12 before |
| XGBoost | One global model across all 90 product-region series, predicting the log ratio to *m − 12* |

- **WMAPE** = Σ|actual − forecast| ÷ Σ actual × 100. Large and small products are weighted by volume.
- **MAE** = average |actual − forecast| in cases per product, region and month. This is the
  unit that turns into stock and money.
- **ML gain** = the error of the best simple rule minus the error of XGBoost. The best rule is
  picked per row **after** seeing the results, which favours the rules. So the gains shown
  are conservative.

## 4. Results on the committed data (1,062 forecasts, 2025)

| Segment | Forecasts | Last month | Same month LY | LY × 3m growth | LY × 12m growth | XGBoost | ML gain (WMAPE pts) | ML gain (MAE, cases) |
|---|---|---|---|---|---|---|---|---|
| All | 1,062 | 14.3 | 16.2 | 14.7 | 13.2 | **10.0** | 3.2 | 43.7 |
| Never-promoted products | 630 | 11.7 | 15.4 | 12.5 | 11.5 | **10.0** | 1.5 | 22.8 |
| Promoted products, other months | 373 | 16.7 | 14.1 | 16.9 | 13.8 | **9.0** | 4.8 | 51.8 |
| Promotion months | 59 | 30.7 | 34.2 | 28.5 | 28.3 | **14.2** | **14.1** | **216.2** |

The best simple rule is *last year × 12-month growth* in every segment. The app's Forecast tab
shows the same table by category, region and month.

**By month:** XGBoost does not beat the best rule in January, February, July or August.
In those months *last month* or *last year × 12-month growth* is as good or better.

**Per series:** an average can hide a model that wins big on a few series and loses on many.
Over all of 2025, against the one fixed rule *last year × 12-month growth*:

| | Series | XGBoost better on | Median gain |
|---|---|---|---|
| Never-promoted products | 54 | 57% | +0.4 pts |
| Promoted products | 36 | 92% | +6.9 pts |

## 5. Independent check: 10 datasets never used in development

`python -m scripts.independent_check` (seeds 101–110; results in
[independent_check.csv](independent_check.csv)). WMAPE points, positive = ML better:

| Segment | Mean ML gain | Range across seeds | Seeds where ML was better |
|---|---|---|---|
| All | 3.8 | 2.5 to 4.9 | 10 of 10 |
| Never-promoted products | 1.1 | 0.1 to 1.6 | 10 of 10 |
| Promoted products, other months | 4.7 | 2.7 to 5.8 | 10 of 10 |
| Promotion months | **16.8** | 13.9 to 20.2 | 10 of 10 |

Per series, across the 10 datasets: XGBoost beat *last year × 12-month growth* on **59%** of
never-promoted series (median gain +0.5 pts) and on **94%** of promoted series (+6.9 pts).

**The development result holds on unseen data.** What this check does **not** show: the 10
datasets come from the same generator, with the same kinds of pattern. They test whether the
result is a fluke of one random draw, not whether it holds on real data.

## 6. Stress test: messier data

`python -m scripts.when_does_ml_win` (6 scenarios × 3 seeds, all 4 simple rules). As noise,
unstable growth and series-to-series differences increase:
- the ML gain in **promotion months** falls from 15.7 to **7.3 points**, but stays clearly positive;
- the gain on **never-promoted products** falls to **0.1–1.4 points**: effectively nothing.

## 7. Recommendation

| Product group | Recommended method | Why |
|---|---|---|
| Promoted products | XGBoost, with the promotion calendar as an input | 14–17 points better in promotion months, on 92–94% of series, and on every unseen dataset |
| Never-promoted products | Last year × 12-month growth | ML is better on only ~6 series in 10, by ~0.5 pts. That isn't worth the cost of building, monitoring and explaining a model |

**Before deploying on real data:** repeat this walk-forward test on the company's own
history. On real distributor data (my MSc dissertation, a separate study), ML was
statistically indistinguishable from the seasonal-naive rule. This synthetic study shows
where to look for value, not that the value exists in a given business.
