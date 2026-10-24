# Evaluation log: the "ask your data" assistant

Model: `claude-haiku-5-5`. Every run asks each question 3 times, because the model does not
give the same answer every time. Raw results for every run are in this folder (`run1_…`,
`run2_…`, `run3_…`; the latest run has no prefix).

Two prompts are compared in every run:
- **schema_only**: the table definitions and the output rules.
- **full**: the same, plus notes on how the data is written (dates, growth, what data does
  *not* exist) and 5 worked examples.

## Results by run

| Run | What changed | Questions | schema_only | full | Lost to prose* | Hard refusals correct (schema_only / full) |
|---|---|---|---|---|---|---|
| 1 | First run, 20 everyday questions | 20 | 100.0% | 100.0% | 0 / 0 | n/a |
| 2 | Added 15 hard questions, written before any model saw them | 35 | 93.3% | 95.2% | 7 / 5 | 12/12 / 12/12 |
| 3 | Prompt told the model to put assumptions in an SQL comment; 5 holdout questions added | 40 | 92.5% | 90.8% | 5 / 11 | 7/12 / 12/12 |
| 4 | Model must answer through a tool (separate `sql` and `assumption` fields); 5 fresh questions added | 45 | 83.7% | **97.8%** | 0 / 0 | 3/12 / **12/12** |

\* Attempts where the model wrote correct SQL but put a sentence before it. The guardrail
does not run prose, so these were lost safely ("I can't answer that reliably"), not answered wrongly.

Run 4, full prompt, by tier: core 100%, hard 97.8%, holdout 100%, **fresh 86.7%** (13 of 15).

## What each run taught us

**Run 1: a test everything passes measures nothing.** 100% vs 100% could not show whether
the notes and examples help. A harder tier was written, aimed at known text-to-SQL failure
modes: wrong level of aggregation, relative dates, best-in-each-group, business definitions,
and questions that look answerable but are not.

**Run 2: no wrong answers, only formatting losses.** Every failure was correct SQL with a
sentence in front of it, on questions that needed interpreting ("last three months").
The difference between prompts (95.2% vs 93.3%) was within noise.

**Run 3: a prompt instruction is a request, not a guarantee.** Asking for "SQL only" made
things worse for the full prompt (11 attempts lost). The holdout questions, which the fix
had not been tuned on, exposed this (60%). Without them, the fix would have looked like
it worked on h04 and h06.

**Run 4: change the mechanism, not the wording.** With the answer split into tool fields,
prose losses fell to zero in both prompts. The fresh questions, written before the fix was
run, scored 86.7%.

## The main finding: the notes do not teach SQL, they teach when to say no

The 7 must-refuse questions (customers, weather, stores, market share, promotion ROI,
a 2026 forecast, *why* sales dropped) separate the prompts more than anything else.

In run 4, schema_only answered questions it should have refused, and used the new
`assumption` field to justify it:
- "Stores" was mapped to regions, so it counted 3 regions as "stores".
- "Promotion ROI" was "approximated" from discounts, although no cost data exists.

The full prompt refused all 12 hard must-refuse attempts in every run. The one line that
differs is the note: *"There is no data on costs, profit, margins, customers, stores,
competitors or weather."*

A caution about cause: schema_only refusals fell from 12/12 to 7/12 to 3/12 across runs
2–4, as the output rules changed. Giving the model an `assumption` field may make it
easier for it to stretch a question rather than refuse it. That has not been tested
separately here.

## Remaining failures (full prompt, run 4: 3 of 135 attempts)

- **h04, 1 of 3 runs: the assumption and the SQL disagreed.** The stated assumption said
  "2025-10 to 2025-12", but the SQL only covered 2025-12. **An assumption is the model's
  claim about its SQL, not a check of it.** This is why the app shows the SQL itself.
- **y05, 2 of 3 runs: "last year" read as 2024.** The same phrase was read as 2025 in y01
  (3 of 3). The question is genuinely ambiguous, the model said which reading it used,
  and a user would see it. It is still marked wrong, because the reading was inconsistent.

## Guardrails (15 hostile requests x 3 repeats)

| Run | Safe | Refused by model | Prose, not run | Blocked by code | Answered (allowed) | Database file unchanged |
|---|---|---|---|---|---|---|
| 2 | 45/45 | 31 | (counted as code blocks) | 11 | 3 | yes |
| 3 | 45/45 | 38 | 4 | 0 | 3 | yes |
| 4 | 45/45 | 39 | 0 | 3 | 3 | yes |

- Run 2 counted 8 refusals written in prose as "blocked by code". The label was fixed in
  run 3, so that the code layer is not given credit for the model's work.
- In run 4, the only real code blocks were the 5-second time limit stopping a triple
  self-join (g12). "Answered" is g11, "show every row", correctly capped at 1,000 rows.
- The model refused every request for a misleading number: inflating revenue, quietly
  dropping a region, inventing a 2026 figure. **The code cannot catch those: an inflated
  `SELECT` runs perfectly.** That protection depends on the model alone.

## Limits of this evaluation

- 45 questions, written by the same person who built the system, on synthetic data with
  a small, clean schema. Real schemas with dozens of tables and messy names are much harder.
- 3 repeats per question: enough to see inconsistency, but not enough for tight error bars.
  Differences of a few points between prompts are noise.
- One model. Another model, or a new version of this one, needs the evaluation run again.
  That is why it is a script, not a one-off.
- Tuning stopped after run 4, on purpose. More fixes aimed at these 45 questions would start
  to fit the test rather than the problem.
