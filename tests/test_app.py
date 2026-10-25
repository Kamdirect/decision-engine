"""The app runs end to end in a headless browser substitute (Streamlit AppTest).
A fake model is used: no API calls, no cost, and the real API key is never read."""

from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import src.assistant as assistant

APP = "../app.py"  # relative to this test file


class ToolClient:
    def __init__(self, name: str, **tool_input):
        self.block = SimpleNamespace(type="tool_use", name=name, input=tool_input)
        self.messages = self

    def create(self, **kwargs):
        return SimpleNamespace(content=[self.block])


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """No real key from the environment, .env or Streamlit secrets; fresh caches each test."""
    import streamlit as st
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(assistant, "_default_client", lambda: None)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def test_all_three_tabs_render_without_errors():
    at = run_app()
    assert [t.label for t in at.tabs] == ["Dashboard", "Forecast", "Ask the data"]
    assert at.metric[0].label == "Revenue" and at.metric[0].value.startswith("£")
    assert any("Read the South's growth with care" in w.value for w in at.warning)


def test_forecast_table_has_every_method_and_segment():
    at = run_app()
    table = at.dataframe[1].value  # [0] is the regions table
    assert {"XGBoost", "Same month last year", "ML gain vs best rule (pts)"} <= set(table.columns)
    assert len(table) == 4  # all forecasts + 3 segments


def test_dashboard_year_switch():
    at = run_app()
    at.radio[0].set_value("2023").run()
    assert not at.exception
    assert not at.metric[0].delta  # no 2022 to compare with


def test_ask_without_a_key_explains_instead_of_crashing():
    at = run_app()
    at.text_input[0].set_value("What was total revenue in 2025?").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("no API key" in e.value for e in at.error)


def test_ask_shows_data_sql_and_assumption(monkeypatch):
    monkeypatch.setattr(assistant, "_default_client", lambda: ToolClient(
        "run_query", sql="SELECT ROUND(SUM(revenue_gbp), 2) AS revenue FROM sales "
                         "WHERE month BETWEEN '2025-10' AND '2025-12'",
        assumption="The last three months are 2025-10 to 2025-12."))
    at = run_app()
    at.text_input[0].set_value("Revenue over the last three months?").run()
    at.button[0].click().run()
    assert not at.exception
    assert any("Assumption made" in i.value for i in at.info)
    assert at.code[0].value.startswith("-- Assumption")
    assert at.dataframe[-1].value.iloc[0, 0] > 0
    assert any(c.value.startswith("9 of 10 questions left") for c in at.caption)  # counts this one


def test_a_refusal_is_shown_as_a_refusal(monkeypatch):
    monkeypatch.setattr(assistant, "_default_client",
                        lambda: ToolClient("cannot_answer", reason="There is no cost data."))
    at = run_app()
    at.text_input[0].set_value("What was our profit margin?").run()
    at.button[0].click().run()
    assert any("There is no cost data." in w.value for w in at.warning)


def test_question_limit_disables_the_button():
    at = run_app()
    at.session_state["questions_asked"] = 10
    at.text_input[0].set_value("anything").run()
    assert at.button[0].disabled
