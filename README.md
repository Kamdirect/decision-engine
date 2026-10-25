# Commercial Decision Engine

[![tests](https://github.com/Kamdirect/decision-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Kamdirect/decision-engine/actions/workflows/tests.yml)

**Live app:** _link added after deployment_

Forecasting and self-serve analytics for an FMCG drinks business, built to show **where each
tool can be trusted and where it cannot**.

> **All data is synthetic.** Meridian Drinks Co. is fictional. `src/synthetic_data.py`
> generates 30 products, 3 regions and 36 months (2023 to 2025) from a fixed seed, shaped
> like a real FMCG distributor's data. No real company data is used. See
> [docs/data_dictionary.md](docs/data_dictionary.md).

## Executive summary

- **Where to invest in machine learning:** XGBoost cuts forecast error by **14.1 points**
  against the best simple rule in promotion months, and beats it on **92%** of promoted
  product-region series. On never-promoted products it is close to a coin flip: better on
  57% of series, by a median of 0.4 points. The gain comes from information the rules
  ignore (the planned promotion calendar). It held on **10 of 10 datasets never used in
  development** (promotion-month gain 13.9–20.2 points).
- **Self-serve analytics that can be trusted:** a plain-English-to-SQL assistant answers
  **97.8%** of 45 hand-checked questions correctly, and handled **all 45** hostile attempts
  safely without changing the database. The most valuable line in its instructions says
  what data does **not** exist: it raised correct refusals from **9 of 21 attempts to 21 of 21**.
- **The caveat that matters:** the data is synthetic. On real distributor data in my MSc
  dissertation (a separate study), ML was statistically indistinguishable from the
  seasonal-naive rule. So the recommendation is to test on your own history first.

## Business problem

A commercial team at a drinks company works from three questions:

1. **What happened?** Which products, categories and regions are growing, and is that growth real?
2. **What will happen?** How much will each product sell next month, by region?
3. **What about my own question?** Answers to ad-hoc questions without waiting days for an analyst.

Two common answers carry real risk. **Machine-learning forecasts** are often bought before
anyone checks whether they beat a simple rule. **AI assistants that query data** can return
a confident, wrong number. This project builds all three capabilities and measures where
each one earns trust.

## Objectives

- Compare a machine-learning forecast with the **best** of four simple rules, on unseen months.
- Find **where** machine learning adds value, rather than reporting one average.
- Build a plain-English-to-SQL assistant whose numbers always come from the database.
- Measure the assistant's accuracy and safety with a test written in advance, rather than
  judging it on a few demonstrations.
- Put everything in one app a non-technical user can open.

## The app

| Tab | What it does | The trust question it answers |
|---|---|---|
| **Dashboard** | Revenue, volume and growth by year, category and region | Is the headline growth real, or partly a base effect? |
| **Forecast** | Forecasts each month of 2025 with 4 simple rules and XGBoost, and scores them by promotion status, category, region and month | Is machine learning worth it, and *where*? |
| **Ask the data** | Turns a plain-English question into SQL and runs it on a read-only database, showing the SQL and any assumption with every answer | How often is it right, and what stops it doing harm? |

## Methodology

### Data
A SQLite database with 4 tables (regions, products, promotions, sales), holding 3,114
monthly sales rows. Known patterns are **planted** so that results can be checked against
the truth:

- summer seasonality
- 6–20% annual growth
- planned promotions on 12 products
- 3 launches in 2024
- 1 delisting
- a supply disruption (South, Carbonated, July 2024, volume × 0.65)

### Forecasting
- **Baselines:** last month (non-seasonal); same month last year (seasonal naive); and the
  same month last year adjusted by recent growth (3-month and 12-month versions).
- **Model:** one global XGBoost model across all 90 product-region series. It predicts the
  ratio to the same month last year, because tree models cannot extrapolate growth. Its
  inputs are recent growth, the planned promotion calendar, seasonality, product age,
  category and region. Every input is known at forecast time; the promotion calendar is
  planned in advance. Its settings were fixed and never tuned.
- **Validation:** walk-forward. Each month of 2025 is forecast using only the months before
  it. A test checks that no future data reaches the model.
- **Metrics:** WMAPE (total absolute error as a % of actual volume) and MAE (cases per
  product-region-month). XGBoost is credited only for beating the **best** simple rule.
  Results are also reported per product-region series, so an average can't hide where it loses.
- **Development vs test:** two design choices were made after seeing 2025 results on the
  committed data, so that period is no longer untouched. The clean test is a re-run on
  **10 datasets (seeds 101–110) never used in development**.
- **Robustness:** the same comparison on 6 progressively messier versions of the data, 3 seeds each.
- Full procedure, feature availability and recommendation: [docs/forecast_evaluation.md](docs/forecast_evaluation.md).

### Ask-the-data assistant
- A large language model is given the table structure, notes on how the data is written
  (including what data does **not** exist), and 5 worked examples. It answers by calling one
  of two tools: `run_query` (separate `sql` and `assumption` fields) or `cannot_answer`.
- **The model never sees the data.** Our code checks the SQL and runs it, so every number
  shown comes from the database. The SQL and any assumption are always shown.
- **Guardrails in code:** only one statement, only `SELECT`/`WITH`, write and admin keywords
  blocked, a read-only connection, a 1,000-row cap and a 5-second time limit.
- **Evaluation:** 45 questions with hand-checked correct SQL, in four tiers:
  - 20 everyday questions
  - 15 hard questions aimed at known text-to-SQL failures
  - 5 holdout questions
  - 5 fresh questions written before the final change

  7 of the 45 questions cannot be answered from the data, and the correct response is a
  refusal (7 questions × 3 runs = 21 attempts). An
  answer is marked on its **result**, not its SQL text. Each question is asked 3 times, and
  the full prompt is compared with a schema-only prompt.
- **Guardrail test:** 15 hostile requests, each 3 times. It records which layer stopped each
  one and checks that the database file is unchanged byte for byte.

## Results

### 1. Forecasting: ML wins where it has information the simple rules don't

1,062 forecasts for 2025. WMAPE in %, lower is better:

| Segment | Last month | Same month last year | × 3-month growth | × 12-month growth | XGBoost | ML gain (pts) | ML gain (MAE, cases) |
|---|---|---|---|---|---|---|---|
| All forecasts | 14.3 | 16.2 | 14.7 | 13.2 | 10.0 | 3.2 | 43.7 |
| Never-promoted products | 11.7 | 15.4 | 12.5 | 11.5 | 10.0 | 1.5 | 22.8 |
| Promoted products, other months | 16.7 | 14.1 | 16.9 | 13.8 | 9.0 | 4.8 | 51.8 |
| **Promotion months** | 30.7 | 34.2 | 28.5 | 28.3 | 14.2 | **14.1** | **216.2** |

*Figures from Linux (GitHub Actions and the deployed app). On Windows, XGBoost differs in
the last decimal place (for example 9.9 instead of 10.0); the conclusions do not change.*

**Per series** (against *last year × 12-month growth*, over all of 2025): XGBoost is better
on **92%** of promoted product-region series (median +6.9 pts), but on only **57%** of
never-promoted series (median +0.4 pts). By month, it doesn't beat the best rule in
January, February, July or August.

**Independent check on 10 unseen datasets** (`scripts/independent_check.py`): the ML gain is
**13.9 to 20.2 points** in promotion months and **0.1 to 1.6** on never-promoted products.
ML was better in every dataset, but on never-promoted products by too little to matter. The
datasets come from the same generator, so this rules out a lucky draw, not a gap with real data.

**Stress test on messier data** (`scripts/when_does_ml_win.py`): the promotion-month gain falls
from 15.7 to **7.3 points** as noise grows, but stays clearly positive. On never-promoted
products it falls to **0.1–1.4 points**.

### 2. Ask the data: 97.8% on 45 hand-checked questions; all 45 hostile attempts handled safely

| | Schema-only prompt | Full prompt |
|---|---|---|
| All 45 questions (135 attempts) | 83.7% | **97.8%** |
| 5 fresh questions, written before the final change | 80.0% | **86.7%** |
| "Must refuse" questions: 7 questions × 3 runs (no cost, customer, store or competitor data) | 9 of 21 | **21 of 21** |

**The extra notes in the prompt don't help the model write SQL. They help it know when to
say no.** Without the line *"There is no data on costs, profit, margins, customers, stores,
competitors or weather"*, the model invented answers. It counted 3 regions as "stores", and
estimated promotion "ROI" with no cost data.

**Guardrails:** 15 hostile requests × 3 runs = 45 attempts. All 45 were handled safely,
and the database file was unchanged byte for byte. The requests included deleting data, prompt injection, attaching other databases, runaway queries, and
requests to inflate or hide numbers. The model refused 39. The 5-second limit stopped 3
runaway queries. The other 3 were "show every row", which is allowed and is capped at 1,000 rows.

The full record of all 4 evaluation runs is in [docs/evaluation_log.md](docs/evaluation_log.md).

## What went wrong, and what changed

- **The first test was too easy.** Both prompts scored 100% on 20 everyday questions, which
  shows nothing. 15 hard questions were added, written before any model saw them.
- **The first fix failed.** The model kept writing a sentence before correct SQL, and the
  guardrail rightly refused to run it. Asking for "SQL only" made things worse (11 attempts
  lost). Holdout questions the fix had not been tuned on exposed this (60%). The fix that
  worked changed the **mechanism**: answers now come through separate tool fields, and
  losses fell to zero.
- **The obvious shortcut was rejected.** Pulling SQL out of the model's sentences would have
  run `SELECT * FROM sales` from inside one of its own refusals.
- **The guardrail report over-credited the code.** It counted 8 refusals written in prose as
  "blocked by code". They were relabelled, so each safety layer gets accurate credit.
- **Tuning stopped after 4 runs, on purpose.** More fixes aimed at the same 45 questions
  would start to fit the test rather than the problem.

## Business implications

- **Forecasting: invest in ML where there is information the simple rules ignore.** Here,
  that is the promotion calendar. For steady, never-promoted products, a simple growth-adjusted
  rule gets most of the accuracy, at no cost and with full transparency. **On real
  distributor data in my MSc dissertation, ML was statistically indistinguishable from the
  seasonal-naive rule.** So before
  paying for a model, test it on your own history in this walk-forward way.
- **Self-serve analytics: suitable for lookups on a clean, documented schema, with the SQL
  shown.** It is not yet suitable for board-level numbers without an analyst checking them.
- **The most valuable line in the prompt says what data does not exist.** Documenting gaps
  matters more than adding examples.
- **Read growth figures with care.** The South's +16.6% volume growth in 2025 is partly a
  recovery from the July 2024 disruption. The SQL behind it is correct, but the conclusion
  would mislead. The dashboard flags this.
- **Re-run the evaluation whenever the model changes.** That is why it is a script, not a one-off.

## Limitations

- **Synthetic data with planted patterns.** The methods detect patterns that were put there.
  That doesn't prove the patterns exist in real markets, and the real-data dissertation
  found no reliable ML advantage.
- **The evaluation is small and partly circular.** It has 45 questions, written by the
  project's author, on a clean 4-table schema. Real schemas are much harder, and differences
  of a few points are noise.
- **A stated assumption is the model's claim, not a check.** In one attempt, the assumption
  said "October to December" while the SQL covered only December. That is why the SQL is
  always shown.
- **One model** (`claude-haiku-5-5`). Another model, or a new version of this one, needs the
  evaluation run again.
- **The code cannot catch dishonest queries.** `SELECT SUM(revenue) * 1.1` runs perfectly.
  Refusing to inflate numbers depends on the model alone.

## Technology stack

| Area | Tools |
|---|---|
| Language | Python 3.13 |
| Data and modelling | pandas, NumPy, XGBoost, SQLite |
| Language model | Anthropic Claude API (`claude-haiku-5-5`, tool calls) |
| App | Streamlit, Altair |
| Testing and CI | pytest (69 tests), Streamlit AppTest, GitHub Actions |

## Run it yourself

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m pytest                # 69 tests, no API key needed: a fake model is used
python -m streamlit run app.py
```

"Ask the data" needs an Anthropic API key in a `.env` file (`ANTHROPIC_API_KEY=...`), which is
git-ignored. Without one, the other two tabs still work and the assistant says it is
unavailable.

| To reproduce | Command | Cost |
|---|---|---|
| The database | `python -m src.synthetic_data` | free |
| The ML stress test | `python -m scripts.when_does_ml_win` | free, about 1 minute |
| The independent forecast check | `python -m scripts.independent_check` | free, about 30 seconds |
| The 45-question evaluation | `python -m scripts.evaluate_assistant` | API, under £1 |
| The guardrail test | `python -m scripts.evaluate_guardrails` | API, a few pence |

## Project structure

```
app.py                    Streamlit app (3 tabs)
src/synthetic_data.py     Builds data/sales.db from a fixed seed
src/forecast.py           Baselines, XGBoost, walk-forward validation, WMAPE
src/assistant.py          Text-to-SQL: prompt, tools, guardrails, read-only execution
src/eval_set.py           The 45 questions and their correct SQL
src/grading.py            Marks answers by comparing results, not SQL text
src/guardrail_set.py      The 15 hostile requests
src/guardrails_eval.py    Records which safety layer stopped each request
scripts/                  Runnable experiments and evaluations
tests/                    69 tests, including leakage, guardrail and app tests
docs/                     Data dictionary, evaluation log, every run's raw results
```
