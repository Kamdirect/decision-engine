# Business case: is ML promotion forecasting worth building?

**Recommendation:** build it for **promoted products only**. Over 3 years it is likely to pay
for itself: median net value about **£44k**, with roughly a **1 in 7 chance of losing money**.
Never-promoted products alone would never pay for the build (about £7k a year saved, against
about £100k of cost over 3 years). **Before committing, measure one number on real data:** the
share of a stock shortfall that is lost to competitors. It moves the result more than every
other assumption.

> Figures are from the saved run (Windows). The live app runs on Linux, where XGBoost
> differs slightly, so its numbers can differ by about £1–2k; no conclusion changes.
>
> Everything here is synthetic and assumption-driven. These are **scenario estimates, not
> measured savings.** Reproduce with `python -m scripts.business_case`; results are saved in
> [business_case.csv](business_case.csv).

## 1. The decision

| | |
|---|---|
| **Decision-maker** | Commercial or supply-chain director |
| **Decision** | Build and run an ML forecast, or keep the simple rule (*last year × 12-month growth*), and for which products |
| **Cost of a wrong decision** | Paying for a model that saves less than it costs; or keeping a rule that over-stocks and under-stocks promotions |
| **Evidence used** | One year (2025) of walk-forward forecasts from [forecast_evaluation.md](forecast_evaluation.md), valued at list price |

## 2. How a forecast error becomes money

Stock for each product, region and month is ordered to the forecast.

| Error | What happens | Cost of £1 of error at list price |
|---|---|---|
| **Over-forecast** | Extra stock is held for a month, then sold. A small share is written off | holding rate ÷ 12 × (1 − margin) + write-off share |
| **Under-forecast** | Part of the shortfall is lost to competitors; the rest is substituted or delayed | gross margin × lost share |

At the midpoint assumptions, £1 of under-forecast costs **£0.16** and £1 of over-forecast
costs **£0.04**. **A missed sale costs about 4 times more than a month of extra stock.**

## 3. Assumptions

Each assumption is sampled uniformly between its low and high values, 10,000 times together.

| Assumption | Low | High | Why |
|---|---|---|---|
| Gross margin | 25% | 40% | Typical range for branded soft drinks at distributor level |
| Share of a shortfall lost to competitors | 30% | 70% | Wide on purpose: substitution varies by brand strength |
| Holding cost per year (share of stock cost) | 15% | 30% | Common textbook range: capital, warehousing, handling |
| Excess stock written off | 0% | 5% | Short-dated stock discounted or scrapped |
| Build cost (one-off) | £20k | £60k | About 2–6 months of one analyst |
| Running cost per year | £10k | £30k | Monitoring, retraining, fixing data feeds, explaining forecasts |

## 4. Results

| | Low (5th pct) | Median | High (95th pct) | Chance below zero |
|---|---|---|---|---|
| Yearly saving: promoted products | £31k | £47k | £68k | 0% |
| Yearly saving: never-promoted products | £5k | £7k | £9k | 0% |
| 3-year net: built for promoted products only | −£19k | **£44k** | £113k | **14%** |
| 3-year net: built for never-promoted products only | −£115k | −£80k | −£44k | 100% |
| 3-year net: built for all products | −£4k | £64k | £140k | 6% |

**What drives the result** (correlation with the 3-year value for promoted products):

| Assumption | Correlation |
|---|---|
| Share of a shortfall lost | +0.72 |
| Running cost | −0.43 |
| Gross margin | +0.41 |
| Build cost | −0.29 |
| Write-off share | +0.19 |
| Holding rate | +0.02 |

**The break-even point for the key assumption:** with every other assumption at its midpoint,
the 3-year case for promoted products breaks even when about **a third** of a shortfall is
lost to competitors. At 30% it is −£7k; at 50%, +£43k.

**Scale matters.** Savings grow with volume, but build and running costs mostly don't. This
business sells about £16.4m a year at list price. For promoted products, the break-even size
is about **£11.3m a year** (90% range £6.7m to £19.4m). A business much smaller than that
should keep the simple rule.

## 5. What this means

1. **The build decision rests entirely on promoted products.** There, the model uses
   information the simple rule can't: the promotion calendar.
2. **For never-promoted products, the simple rule is the right default.** Once the model
   exists, adding them saves about £7k a year at little extra cost, so it's optional. But
   XGBoost beats the rule on only about 6 in 10 of those series, which makes the forecasts
   harder to explain to planners.
3. **Measure substitution before deciding.** Most of the uncertainty is about how much
   demand is lost when stock runs out. A short review of past stockouts would narrow the
   range more than any modelling work.
4. **Running cost matters more than build cost.** It's paid every year. A cheaper,
   well-monitored pipeline improves the case more than a cheaper build does.

## 6. Limits

- **One year of synthetic data**, with patterns planted by design. The model's advantage in
  promotion months is likely to be smaller on real data. My MSc dissertation found no
  reliable ML advantage on real distributor data.
- **No safety stock or lead times.** Real ordering holds buffer stock, which turns some lost
  sales into extra holding cost. That would lower the value of better forecasts.
- **One cost per case for all products,** based on list price. Promotional discounts and
  product-specific margins are ignored.
- **Uniform, independent assumption ranges.** In reality, high-margin products may also
  suffer more substitution. Correlated assumptions would widen the range.
