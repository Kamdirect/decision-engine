"""Grade the assistant against the 20 hand-checked questions.

How an answer is marked correct:
  - Answerable question: the assistant's result must contain the same values as the gold
    result. Same number of rows; every gold column must match one of the assistant's
    columns (extra columns, such as a total shown next to a name, are allowed). Column names
    and row order are ignored, because they do not change the answer. Numbers match within
    0.5% or 0.06, so 16.6 and 16.62 both count, but 0.166 for 16.6% does not.
  - Unanswerable question: correct only if the assistant refuses.
The grading is strict on purpose: a human might accept "all four categories, ranked" as an
answer to "which category was highest", but a dashboard showing four rows would not.
Every failure is saved with its SQL so it can be reviewed by hand.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.assistant import DB_PATH, FORMAT_RULES, SCHEMA, ask, run_sql

# The "before" prompt: table definitions and the same output rules. No notes on how months,
# growth or volume are written, and no worked examples. Comparing it with the full prompt
# shows what the notes and examples add.
SCHEMA_ONLY_PROMPT = f"""You translate business questions into one SQLite query.

{SCHEMA.split("Notes:")[0].strip()}

{FORMAT_RULES}"""

REL_TOL, ABS_TOL = 0.005, 0.06


@dataclass
class Grade:
    correct: bool
    outcome: str   # correct | wrong_answer | should_have_refused | refused_wrongly | error
    detail: str = ""


def _normalise(column: pd.Series) -> list:
    """Numbers as floats, text as lower-case, then sorted so row order does not matter."""
    numeric = pd.to_numeric(column, errors="coerce")
    if numeric.notna().all():
        return sorted(float(v) for v in numeric)
    return sorted(str(v).strip().lower() for v in column)


def _same(a: list, b: list) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if isinstance(x, float) and isinstance(y, float):
            if abs(x - y) > max(ABS_TOL, REL_TOL * abs(y)):
                return False
        elif x != y:
            return False
    return True


def results_match(gold: pd.DataFrame, got: pd.DataFrame) -> tuple[bool, str]:
    if len(gold) != len(got):
        return False, f"{len(got)} rows, expected {len(gold)}"
    unused = list(got.columns)
    for g in gold.columns:
        target = _normalise(gold[g])
        hit = next((c for c in unused if _same(_normalise(got[c]), target)), None)
        if hit is None:
            return False, f"no column matches gold column '{g}' (expected {target[:5]})"
        unused.remove(hit)
    return True, ""


def grade(item: dict, answer, db_path: Path = DB_PATH) -> Grade:
    if item["gold_sql"] is None:
        if answer.refused:
            return Grade(True, "correct", answer.refused)
        return Grade(False, "should_have_refused", answer.error or "answered instead of refusing")
    if answer.refused:
        return Grade(False, "refused_wrongly", answer.refused)
    if answer.error:
        return Grade(False, "error", answer.error)
    ok, why = results_match(run_sql(item["gold_sql"], db_path), answer.data)
    return Grade(ok, "correct" if ok else "wrong_answer", why)


def evaluate(questions: list[dict], prompts: dict[str, str], client=None, repeats: int = 1,
             db_path: Path = DB_PATH, progress=print) -> pd.DataFrame:
    """Ask every question `repeats` times with every prompt. One row per attempt."""
    rows = []
    for name, system in prompts.items():
        for item in questions:
            for run in range(1, repeats + 1):
                answer = ask(item["question"], client=client, db_path=db_path, system=system)
                g = grade(item, answer, db_path)
                rows.append({"prompt": name, "id": item["id"], "tier": item.get("tier", "core"),
                             "kind": item["kind"], "run": run,
                             "correct": g.correct, "outcome": g.outcome, "detail": g.detail,
                             "question": item["question"], "sql": answer.sql,
                             "assumption": answer.assumption})
                progress(f"  {name:<12} {item['id']} run {run}: {g.outcome}")
    return pd.DataFrame(rows)


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Accuracy per prompt, overall and per tier, as % of attempts."""
    overall = results.groupby("prompt")["correct"].mean().mul(100).round(1).rename("ALL")
    by_tier = results.pivot_table(index="prompt", columns="tier", values="correct",
                                  aggfunc="mean").mul(100).round(1)
    return pd.concat([overall, by_tier], axis=1)


def by_kind(results: pd.DataFrame) -> pd.DataFrame:
    """Accuracy per kind of question (rows) and prompt (columns), to see where failures come from."""
    return results.pivot_table(index=["tier", "kind"], columns="prompt", values="correct",
                               aggfunc="mean").mul(100).round(1)


def consistency(results: pd.DataFrame) -> pd.Series:
    """% of questions where every repeat gave the same verdict (the model is not fully repeatable)."""
    same = results.groupby(["prompt", "id"])["correct"].nunique().eq(1)
    return same.groupby("prompt").mean().mul(100).round(1)
