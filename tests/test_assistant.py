"""Tests for the 'ask your data' assistant. A fake model is used: no API calls, no cost."""

from types import SimpleNamespace

import pytest

from src.assistant import EXAMPLES, UnsafeSQL, ask, assumptions, check_sql, clean_sql, run_sql


class FakeClient:
    """Pretends to be the Anthropic client and replies with fixed text."""

    def __init__(self, reply: str = "", fail: bool = False):
        self.reply, self.fail, self.sent = reply, fail, None
        self.messages = self

    def create(self, **kwargs):
        if self.fail:
            raise ConnectionError("network down")
        self.sent = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.reply)])


class ToolClient:
    """Pretends to be the model answering through a tool call, as the live model must."""

    def __init__(self, name: str, **tool_input):
        self.block = SimpleNamespace(type="tool_use", name=name, input=tool_input)
        self.messages = self

    def create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(content=[self.block])


# ------------------------------------------------------------------ guardrails
@pytest.mark.parametrize("sql", [
    "DROP TABLE sales",
    "DELETE FROM sales",
    "UPDATE sales SET volume_cases = 0",
    "SELECT 1; DROP TABLE sales",
    "ATTACH DATABASE 'x.db' AS x",
    "PRAGMA writable_schema = 1",
    "WITH x AS (SELECT 1) DELETE FROM sales",
    "",
])
def test_unsafe_sql_is_blocked(sql):
    with pytest.raises(UnsafeSQL):
        check_sql(sql)


def test_safe_select_passes_and_trailing_semicolon_is_fine():
    assert check_sql("SELECT 1;") == "SELECT 1"


def test_database_is_read_only_even_if_a_guardrail_were_bypassed():
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect("file:data/sales.db?mode=ro", uri=True)) as con:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("DELETE FROM sales")


def test_row_cap():
    df = run_sql("SELECT * FROM sales")
    assert len(df) == 1000


def test_markdown_fences_are_removed():
    assert clean_sql("```sql\nSELECT 1;\n```") == "SELECT 1;"


# ------------------------------------------------------------------ examples are correct
def test_every_worked_example_runs_and_returns_rows():
    for question, sql in EXAMPLES:
        if sql.startswith("CANNOT_ANSWER"):
            continue
        assert not run_sql(sql).empty, question


# ------------------------------------------------------------------ end to end with a fake model
def test_ask_runs_the_generated_sql_and_shows_it():
    sql = "SELECT COUNT(*) AS n FROM regions;"
    a = ask("How many regions are there?", client=FakeClient(sql))
    assert a.error is None and a.sql == sql
    assert a.data.iloc[0]["n"] == 3


def test_ask_blocks_dangerous_sql_from_the_model():
    a = ask("Delete everything", client=FakeClient("DELETE FROM sales;"))
    assert a.data is None and "blocked" in a.error


def test_ask_passes_on_a_refusal():
    a = ask("What is our profit?", client=FakeClient("CANNOT_ANSWER: no cost data."))
    assert a.refused == "no cost data." and a.error is None


def test_ask_reports_empty_results_instead_of_guessing():
    a = ask("Sales in 2030?", client=FakeClient("SELECT * FROM sales WHERE month = '2030-01';"))
    assert "can't answer that reliably" in a.error


def test_ask_never_crashes(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "no API key" in ask("anything").error
    assert "ConnectionError" in ask("anything", client=FakeClient(fail=True)).error
    assert "failed" in ask("bad sql", client=FakeClient("SELECT * FROM nonsense")).error


def test_an_assumption_comment_runs_and_is_shown_to_the_user():
    sql = ("-- Assumption: the data ends in 2025-12, so the last three months are 2025-10 to 2025-12.\n"
           "SELECT SUM(revenue_gbp) AS revenue FROM sales WHERE month BETWEEN '2025-10' AND '2025-12';")
    a = ask("Revenue over the last three months?", client=FakeClient(sql))
    assert a.error is None and a.data.iloc[0, 0] > 0
    assert a.assumption.startswith("the data ends in 2025-12")
    assert assumptions("SELECT 1") is None


def test_prose_before_the_sql_is_still_refused():
    """Deliberately strict. In the guardrail test the model once refused in prose and then
    offered 'SELECT * FROM sales' as an alternative: pulling SQL out of prose would have run it."""
    a = ask("x", client=FakeClient("I can't do that. Instead:\n\nSELECT * FROM sales;"))
    assert a.data is None and "only SELECT" in a.error


# ------------------------------------------------------------------ tool calls (the live path)
def test_the_model_is_forced_to_answer_through_a_tool():
    client = ToolClient("run_query", sql="SELECT COUNT(*) AS n FROM regions")
    a = ask("How many regions?", client=client)
    assert a.data.iloc[0]["n"] == 3 and a.assumption is None
    assert client.sent["tool_choice"] == {"type": "any"}
    assert {t["name"] for t in client.sent["tools"]} == {"run_query", "cannot_answer"}


def test_a_tool_assumption_is_shown_and_a_tool_refusal_is_a_refusal():
    a = ask("Revenue lately?", client=ToolClient(
        "run_query", sql="SELECT SUM(revenue_gbp) FROM sales WHERE month >= '2025-10'",
        assumption="'Lately' means the last three months of data, 2025-10 to 2025-12."))
    assert a.error is None and a.assumption.startswith("'Lately' means")
    r = ask("Market share?", client=ToolClient("cannot_answer", reason="No competitor data."))
    assert r.refused == "No competitor data." and r.data is None


def test_an_assumption_cannot_smuggle_sql_out_of_its_comment():
    """The assumption becomes an SQL comment line. A line break inside it could end the comment
    and add a statement, so line breaks are removed first."""
    a = ask("x", client=ToolClient("run_query", sql="SELECT 1 AS one",
                                   assumption="fine\nDROP TABLE sales"))
    assert a.error is None and a.data.iloc[0]["one"] == 1
    assert "\nDROP" not in a.sql


def test_dangerous_sql_inside_a_tool_call_is_still_blocked():
    a = ask("x", client=ToolClient("run_query", sql="DELETE FROM sales"))
    assert a.data is None and "blocked" in a.error
