# Commercial Decision Engine

[![tests](https://github.com/Kamdirect/decision-engine/actions/workflows/tests.yml/badge.svg)](https://github.com/Kamdirect/decision-engine/actions/workflows/tests.yml)

**Live app:** _link added after deployment_

A sales team at a drinks company wants three things: what happened, what will happen next,
and quick answers to their own questions without waiting for an analyst. This project
builds all three, and then tests where each one can and cannot be trusted.

| Tab | What it does | The trust question it answers |
|---|---|---|
| **Dashboard** | Revenue, volume and growth by year, category and region | Is the headline growth real, or partly a base effect? |
| **Forecast** | Forecasts each month of 2025 with 3 simple rules and XGBoost, scored month by month on unseen data | Is machine learning worth it, and *where*? |
| **Ask the data** | Turns a plain-English question into SQL and runs it on a read-only database, showing the SQL and any assumption with every answer | How often is it right, and what stops it doing harm? |

> **All data is synthetic.** Meridian Drinks Co. is fictional. `src/synthetic_data.py`
> generates 30 products, 3 regions and 36 months (2023 to 2025) from a fixed seed, shaped
> like a real FMCG distributor's data. No real company data is used. See
> [docs/data_dictionary.md](docs/data_dictionary.md).

## Results

### 1. Forecasting: ML wins where it has information the simple rules don't

Walk-forward validation: each month of 2025 is forecast using only the months before it
(1,062 forecasts). The error measure is WMAPE (total absolute error as a % of actual
volume; lower is better). XGBoost is only credited with beating the **best** of three
simple rules, not the weakest.

| Segment | Same month last year | × 3-month growth | × 12-month growth | XGBoost | ML gain (pts) |
|---|---|---|---|---|---|
| All forecasts | 16.2 | 14.7 | 13.2 | 10.0 | 3.2 |
| Never-promoted products | 15.4 | 12.5 | 11.5 | 10.0 | 1.5 |
| Promoted products, other months | 14.1 | 16.9 | 13.8 | 9.0 | 4.8 |
| **Promotion months** | 34.2 | 28.5 | 28.3 | 14.2 | **14.1** |

*Figures from Linux (GitHub Actions and the deployed app). On Windows, XGBoost differs in
the last decimal place (for example 9.9 instead of 10.0); the conclusions do not change.*

**Stress test** (`scripts/when_does_ml_win.py`): the same comparison on 6 progressively messier
versions of the data, 3 seeds each. The gain in promotion months stays at **8 to 16 points**.
On never-promoted products it is only **1 to 3 points**.

**Decision rule:** use the model where it has information the rules cannot use. Here that
is the promotion calendar, which is planned in advance. Elsewhere, ask for evidence on your
own data first. **On real distributor data in my MSc dissertation, ML did not beat the
simple rules.** That is why these synthetic results cannot prove real-world value. They
show *where* to look for it.

### 2. Ask the data: 97.8% on 45 hand-checked questions, 45 of 45 hostile requests stopped

The assistant was graded on 45 questions with hand-checked answers, each asked 3 times.
It was compared with a simpler prompt over 4 evaluation runs. The full story, including
what went wrong, is in [docs/evaluation_log.md](docs/evaluation_log.md).

| | Simpler prompt (schema only) | Full prompt |
|---|---|---|
| All 45 questions (135 attempts) | 83.7% | **97.8%** |
| 5 fresh questions, written before the final change | 80.0% | **86.7%** |
| "Must refuse" questions (no cost, customer or competitor data) | 3 of 12 | **12 of 12** |

The main finding: **the extra notes in the prompt don't help the model write SQL. They help
it know when to say no.** Without the line *"There is no data on costs, profit, margins,
customers, stores, competitors or weather"*, the model invented answers. It counted 3
regions as "stores", and estimated promotion "ROI" with no cost data.

**Guardrails** (15 hostile requests × 3, `scripts/evaluate_guardrails.py`): requests to delete
data, prompt injection, attaching other databases, runaway queries, and requests for
deliberately misleading numbers. **All 45 attempts were safe, and the database file was
unchanged byte for byte.** The model refused 39. The code's 5-second time limit stopped 3
runaway queries. The other 3 were "show every row", which is allowed and is capped at
1,000 rows.

## How the assistant is built to be trusted

1. **The AI never sees the data.** It sees the table structure and writes SQL. Our code runs
   the SQL, so every number shown comes from the database.
2. **The SQL is always shown**, together with any assumption the AI made ("the last three
   months means 2025-10 to 2025-12").
3. **Guardrails are in code, not just in the prompt.** Only one statement is allowed, and
   only `SELECT`/`WITH`. Write and admin keywords are blocked. The connection is read-only,
   with a 1,000-row cap and a 5-second time limit.
4. **The AI answers by calling one of two tools**: `run_query` (with separate `sql` and
   `assumption` fields) or `cannot_answer`. A refusal counts as a correct answer.
5. **When unsure, it says so.** Errors and empty results give "I can't answer that
   reliably", never a guess.

## What I got wrong, and fixed

- **My first test was too easy.** Both prompts scored 100% on 20 everyday questions, which
  shows nothing. I added 15 questions aimed at known text-to-SQL failures, written before
  any model saw them.
- **My first fix didn't work.** The model kept writing a sentence before correct SQL, and the
  guardrail rightly refused to run it. Telling the model "SQL only" made things *worse*
  (11 attempts lost). Five holdout questions it hadn't been tuned on exposed this (60%).
  The fix that worked changed the **mechanism**: answers now come through separate tool
  fields, and losses fell to zero.
- **I rejected the obvious shortcut.** "Pull the SQL out of the sentences" would have run
  `SELECT * FROM sales` from inside one of the model's own refusals.
- **My guardrail report over-credited the code.** It counted 8 refusals the model wrote in
  prose as "blocked by code". I relabelled them, so the code layer isn't given credit for
  the model's work.
- **The dashboard chart zoomed when you scrolled over it.** It's now a static chart.

## Limitations

- **Synthetic data with planted patterns.** The methods detect patterns I put there. That
  doesn't prove those patterns exist in real markets, and my real-data dissertation result
  points the other way for ML.
- **The evaluation is small and partly circular.** 45 questions, written by the person who
  built the system, on a clean 4-table schema. Real schemas are much harder. Differences of
  a few points are noise.
- **Correct SQL can still mislead.** "Which region grew fastest?" correctly returns the South
  (+16.6%), but part of that is recovery from a July 2024 supply disruption. The dashboard
  flags this; the assistant does not.
- **The stated assumption is the model's claim, not a check.** In one attempt the assumption
  said "October to December" while the SQL covered only December. That is why the SQL is
  always shown.
- **One model** (`claude-haiku-5-5`). A different model or version needs the evaluation run
  again, which is why it's a script.
- **The code cannot catch dishonest queries.** `SELECT SUM(revenue) * 1.1` runs perfectly.
  Refusing to inflate numbers depends on the model alone.

## Run it yourself

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python -m pytest                # 64 tests, no API key needed: a fake model is used
python -m streamlit run app.py
```

"Ask the data" needs an Anthropic API key in a `.env` file (`ANTHROPIC_API_KEY=...`), which is
git-ignored. Without one, the other two tabs still work and the assistant says it is
unavailable.

| To reproduce | Command | Cost |
|---|---|---|
| The database | `python -m src.synthetic_data` | free |
| The ML stress test | `python -m scripts.when_does_ml_win` | free, about 1 minute |
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
tests/                    64 tests, including leakage, guardrail and app tests
docs/                     Data dictionary, evaluation log, every run's raw results
```

## How I used AI

I built this with Claude (Anthropic) as a mentor. Claude drafted most of the code and
proposed most of the methods, step by step. I ran every step on my own machine, checked the
outputs, and committed each stage only after its tests passed. The reason for each method
is written in the code and in [docs/evaluation_log.md](docs/evaluation_log.md), so that I
can explain and defend it. Examples: crediting ML only against the best simple rule,
writing questions before testing, and stopping tuning after four runs.

The business framing comes from my own work in drinks sales and key accounts: promotions
planned in advance, launches, delistings, supply problems, and growth that is really a base
effect. The assistant inside the app uses `claude-haiku-5-5`; every test
in this repository uses a fake model instead.
