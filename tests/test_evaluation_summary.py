"""The category summary counts correctly (checked on a tiny hand-made results table)."""

import pandas as pd

from scripts.evaluation_summary import correctness, safety


def test_correctness_counts_by_category_and_names_failures():
    results = pd.DataFrame({
        "prompt": ["full"] * 4 + ["schema_only"],
        "id": ["q1", "q1", "q2", "q3", "q1"],
        "kind": ["total", "total", "time", "refuse", "total"],
        "correct": [True, False, True, False, True],
        "outcome": ["correct", "wrong_answer", "correct", "should_have_refused", "correct"],
    })
    table = correctness(results).set_index("category")
    assert table.loc["Totals and lookups", "attempts"] == 2
    assert table.loc["Totals and lookups", "failures"] == "1 wrong result"
    assert table.loc["Unsupported questions (must refuse)", "failures"] == "1 answered instead of refusing"
    assert table.loc["All", "correct"] == 2 and table.loc["All", "questions"] == 3


def test_safety_counts_each_layer():
    guard = pd.DataFrame({"id": ["g1", "g1", "g2"], "kind": ["write", "write", "resource"],
                          "safe": [True, True, True],
                          "outcome": ["refused_by_model", "refused_by_model", "blocked_by_code"]})
    table = safety(guard).set_index("category")
    assert table.loc["Change data", "how"] == "2 refused by model"
    assert table.loc["Overload the database", "safe"] == 1
