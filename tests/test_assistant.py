"""Tests for the 'ask your data' assistant. A fake model is used: no API calls, no cost."""

from types import SimpleNamespace

import pytest

from src.assistant import EXAMPLES, UnsafeSQL, ask, check_sql, clean_sql, run_sql


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
