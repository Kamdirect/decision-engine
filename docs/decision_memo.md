# Decision memo: forecasting and self-serve analytics at Meridian Drinks Co.

**To:** Commercial Director · **Re:** whether to invest in ML demand forecasting and an
"ask the data" assistant · **Basis:** synthetic data for a fictional company (2023–2025);
scenario estimates, not measured savings

## Decision

**Build an ML forecast for promoted products only, after a two-week check of stockout
losses. Keep the simple rule (*last year × 12-month growth*) for every other product.
Release the data assistant for internal lookups, with the SQL always visible. Don't use it
for board figures without an analyst's sign-off.**

## Evidence: the three findings that matter

1. **ML only adds value where it has information the rules don't: the promotion calendar.**
   - In promotion months, XGBoost cuts forecast error by **14 points** (WMAPE 14% against 28%
     for the best simple rule).
   - It is better on **92%** of promoted product-region series.
   - On never-promoted products it is close to a coin flip: better on **57%** of series, by
     a median of 0.4 points.
   - The result held on 10 of 10 datasets never used in development.
2. **It is worth paying for, but only for promoted products, and only at this scale.**
   - Over 3 years, after an assumed £20–60k build and £10–30k a year to run, a model for
     promoted products has a median net value of about **£44k**, with a **14% chance of
     losing money**.
   - For never-promoted products alone, it never pays back.
   - Break-even is about £11m of annual sales; this business sells £16m.
3. **The assistant is accurate on a clean schema, and refuses what it can't answer.**
   - It answered **97.8%** of 135 test attempts correctly, and refused all 21 attempts at
     questions the data cannot answer.
   - All 45 hostile attempts were handled safely, and the database was unchanged.
   - Its 3 errors were on ambiguous questions ("last year", "last three months").

## Trade-offs and risks

| Risk | Size | Mitigation |
|---|---|---|
| The savings depend most on **how much of a stockout is lost to competitors** (assumed 30–70%) | It moves the 3-year value more than any other input | Measure it from past stockouts before committing |
| Results are on **synthetic data**. On real distributor data (my MSc dissertation), ML was statistically indistinguishable from the seasonal-naive rule | The promotion advantage may be smaller in practice | Repeat the walk-forward test on the company's own history first |
| Promotions added at short notice would remove the model's information advantage | Unknown | Check how far ahead promotions are fixed |
| The assistant gives **correct SQL with a misleading conclusion**. Example: the South's +16.6% "growth" is partly recovery from a 2024 supply disruption | The answer passes every check, yet misleads | Show the SQL and the assumption with every answer; flag known base effects on the dashboard |
| Running cost is paid every year; build cost once | Running cost moves the result more than build cost | Keep the pipeline simple and monitored |

## Recommendation and next steps

| Step | Owner | When | Go/no-go test |
|---|---|---|---|
| 1. Measure the share of stockout demand lost, from the last 12 months of stockouts | Supply chain | 2 weeks | If under about a third is lost, stop: at mid-range costs the 3-year case breaks even at about 33% |
| 2. Re-run the forecast comparison on the company's real history | Analytics | 3 weeks | ML must beat the simple rule in promotion months on real data |
| 3. Pilot the model for promoted products in one region | Analytics + planners | 1 quarter | Forecast error and stockouts fall against the rule-forecast regions |
| 4. Release the assistant to the commercial team for lookups | Analytics | Now | Re-run the 45-question test whenever the model or data changes |

## What would change this recommendation

- **Promotions decided at short notice:** then don't build. The model's advantage comes from
  knowing promotions in advance.
- **A much smaller business** (well under about £11m of sales): keep the simple rule.
- **A real-data test where ML doesn't beat the rule in promotion months:** don't build.
  That was my dissertation's finding on real distributor data.
