"""Tests for the evaluation set and the grader. A fake model is used: no API calls, no cost."""

from types import SimpleNamespace

import pandas as pd

from src.assistant import EXAMPLES, run_sql
from src.eval_set import QUESTIONS
from src.grading import evaluate, results_match, summarise


class ReplayClient:
    """A fake model that replies with whatever SQL (or refusal) we give it for each question."""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.messages = self

    def create(self, **kwargs):
        question = kwargs["messages"][0]["content"].removeprefix("Question: ")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies[question])])


# ------------------------------------------------------------------ the question set itself
def test_45_questions_with_unique_ids_and_seven_refusals():
    assert len(QUESTIONS) == 45
    assert len({q["id"] for q in QUESTIONS}) == 45
    assert [q["tier"] for q in QUESTIONS].count("fresh") == 5
    assert [q["tier"] for q in QUESTIONS].count("holdout") == 5
    assert sum(q["gold_sql"] is None for q in QUESTIONS) == 7
    assert [q["tier"] for q in QUESTIONS].count("hard") == 15


def test_every_hard_question_says_what_its_trap_is():
    assert all(q.get("trap") for q in QUESTIONS if q["tier"] == "hard")


def test_no_test_question_was_shown_to_the_model_as_an_example():
    shown = {q.lower() for q, _ in EXAMPLES}
    assert not shown & {q["question"].lower() for q in QUESTIONS}


def test_every_gold_query_runs_and_returns_rows():
    for q in QUESTIONS:
        if q["gold_sql"]:
            assert not run_sql(q["gold_sql"]).empty, q["id"]


def test_gold_answers_spot_checked_by_hand():
    """Answers checked independently with different SQL or known facts about the data."""
    gold = {q["id"]: q["gold_sql"] for q in QUESTIONS}
    assert run_sql(gold["q03"]).iloc[0, 0] == 29                      # 30 SKUs, 1 delisted
    assert len(run_sql(gold["q15"])) == 3                             # 3 launches in 2024-01
    assert run_sql(gold["q07"]).iloc[0, 0] in {"2024-06", "2024-07", "2024-08"}  # summer peak
    # q12 recomputed a different way: 10,714 cases in 2024-07 vs 11,811 in 2023-07 = -9.3%.
    # Only -9.3% despite a planted -35% shock, because two Carbonated products launched in
    # 2024 add volume that 2023 did not have. Like-for-like (products on sale in both years):
    july = run_sql(
        "SELECT s.month, SUM(s.volume_cases) AS all_cases, "
        "SUM(CASE WHEN p.launch_month = '2023-01' THEN s.volume_cases END) AS like_for_like "
        "FROM sales s JOIN products p USING (product_id) "
        "WHERE s.region_id = 3 AND p.category = 'Carbonated' AND s.month IN ('2023-07', '2024-07') "
        "GROUP BY s.month ORDER BY s.month").set_index("month")
    headline = 100 * (july.loc["2024-07", "all_cases"] / july.loc["2023-07", "all_cases"] - 1)
    like_for_like = 100 * (july.loc["2024-07", "like_for_like"] / july.loc["2023-07", "like_for_like"] - 1)
    assert run_sql(gold["q12"]).iloc[0, 0] == round(headline, 1) == -9.3
    assert like_for_like < -20
    assert len(run_sql(gold["h06"])) == 29                            # all but the delisted one
    assert run_sql(gold["x02"]).iloc[0, 0] == "Cream Soda 500ml"     # the one delisted product
    assert run_sql(gold["x03"]).iloc[0, 0] == "Central"              # biggest by revenue AND volume
    assert run_sql(gold["y04"]).iloc[0, 0] == 6                       # all 6 Water SKUs still listed
    assert len(run_sql(gold["h07"])) == 3                             # one winner per region
    assert run_sql(gold["h02"]).iloc[0, 0] == 12                      # 12 promoted SKUs


def test_the_hard_traps_really_give_different_answers():
    """If the tempting wrong query gave the same result, the question would not test anything."""
    gold = {q["id"]: q["gold_sql"] for q in QUESTIONS}
    tempting = {
        "h01": "SELECT r.region_name, AVG(s.volume_cases) FROM sales s JOIN regions r USING (region_id) "
               "WHERE s.month LIKE '2025-%' GROUP BY r.region_name",
        "h02": "SELECT COUNT(*) FROM promotions WHERE month LIKE '2025-%'",
        "h05": "SELECT month FROM sales WHERE month LIKE '2025-%' GROUP BY month "
               "ORDER BY SUM(volume_cases) DESC LIMIT 1",
        "h06": "SELECT product_name FROM products",
        "h07": "SELECT p.product_name FROM sales s JOIN products p USING (product_id) "
               "WHERE s.month LIKE '2025-%' GROUP BY p.product_name ORDER BY SUM(s.volume_cases) DESC LIMIT 1",
    }
    for qid, wrong in tempting.items():
        assert not results_match(run_sql(gold[qid]), run_sql(wrong))[0], qid


# ------------------------------------------------------------------ the comparison rules
def test_names_order_rounding_and_extra_columns_do_not_matter():
    gold = pd.DataFrame({"region_name": ["North", "South"], "revenue": [100.0, 200.0]})
    got = pd.DataFrame({"total_gbp": [200.004, 100.0], "region": ["south", "North"],
                        "share": [0.67, 0.33]})
    assert results_match(gold, got)[0]


def test_wrong_values_wrong_rows_and_wrong_units_fail():
    gold = pd.DataFrame({"growth_pct": [16.6]})
    assert not results_match(gold, pd.DataFrame({"g": [17.6]}))[0]
    assert not results_match(gold, pd.DataFrame({"g": [0.166]}))[0]          # a share, not a %
    assert not results_match(gold, pd.DataFrame({"g": [16.6, 13.9]}))[0]     # extra rows


# ------------------------------------------------------------------ end to end with a fake model
def test_a_model_that_gives_the_gold_answers_scores_100_percent():
    replies = {q["question"]: q["gold_sql"] or "CANNOT_ANSWER: not in the data" for q in QUESTIONS}
    results = evaluate(QUESTIONS, {"full": "x"}, client=ReplayClient(replies), progress=lambda _: None)
    assert results["correct"].all()
    assert summarise(results).loc["full", "ALL"] == 100.0


def test_a_model_that_always_refuses_only_gets_the_refusals_right():
    replies = {q["question"]: "CANNOT_ANSWER: no" for q in QUESTIONS}
    results = evaluate(QUESTIONS, {"full": "x"}, client=ReplayClient(replies), progress=lambda _: None)
    assert results["correct"].sum() == 7
    assert set(results.loc[~results["correct"], "outcome"]) == {"refused_wrongly"}


def test_a_model_that_answers_everything_fails_the_refusals():
    replies = {q["question"]: "SELECT COUNT(*) FROM sales" for q in QUESTIONS}
    results = evaluate(QUESTIONS, {"full": "x"}, client=ReplayClient(replies), progress=lambda _: None)
    refusals = results[results["kind"] == "refuse"]
    assert set(refusals["outcome"]) == {"should_have_refused"}


def test_both_prompts_share_the_same_output_rules():
    """Otherwise a 'before vs after' difference could just be a formatting difference."""
    from src.assistant import FORMAT_RULES, SYSTEM_PROMPT  # noqa: I001
    from src.grading import SCHEMA_ONLY_PROMPT
    assert FORMAT_RULES in SYSTEM_PROMPT and FORMAT_RULES in SCHEMA_ONLY_PROMPT
