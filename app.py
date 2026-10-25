"""Commercial Decision Engine: what happened, what will happen, and ask your own question.

Run locally:  python -m streamlit run app.py
"""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from src import assistant
from src.forecast import load_panel, score, walk_forward
from src.synthetic_data import COMPANY

ROOT = Path(__file__).parent
DB = ROOT / "data" / "sales.db"
DOCS = ROOT / "docs"
MAX_QUESTIONS_PER_SESSION = 10
TEST_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]
METHOD_NAMES = {"naive": "Same month last year", "growth_3m": "Last year x 3-month growth",
                "growth_12m": "Last year x 12-month growth", "xgboost": "XGBoost"}
SEGMENT_NAMES = {"promotion months": "Promotion months",
                 "promoted SKUs, normal months": "Promoted SKUs, other months",
                 "never-promoted SKUs": "Never-promoted SKUs"}
EXAMPLES = [
    "Which region grew fastest in volume from 2024 to 2025?",
    "What were the top 5 products by revenue in 2025?",
    "What was total revenue over the last three months?",
    "What share of 2025 revenue came from sales on promotion?",
    "What was our profit margin in 2025?",
]

# API key: from .env locally, or from Streamlit "Secrets" when deployed. Never in code.
load_dotenv()
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:  # no secrets file: fine, the assistant will say it is unavailable
    pass


# ------------------------------------------------------------------ data (cached)
@st.cache_data(show_spinner=False)
def load_sales() -> pd.DataFrame:
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as con:
        return pd.read_sql(
            "SELECT s.month, r.region_name AS region, p.product_name AS product, p.category, "
            "s.volume_cases, s.revenue_gbp, s.on_promotion "
            "FROM sales s JOIN regions r USING (region_id) JOIN products p USING (product_id)", con)


@st.cache_data(show_spinner=False)
def forecast_results() -> pd.DataFrame:
    """Walk-forward forecasts for every month of 2025 (about 3 seconds, then cached)."""
    panel = load_panel(DB)
    results = walk_forward(panel, TEST_MONTHS)
    promoted = set(panel.loc[panel["discount_pct"] > 0, "product_id"])
    with closing(sqlite3.connect(f"file:{DB}?mode=ro", uri=True)) as con:
        products = pd.read_sql("SELECT product_id, product_name AS product FROM products", con)
        regions = pd.read_sql("SELECT region_id, region_name AS region FROM regions", con)
    results = results.merge(products, on="product_id").merge(regions, on="region_id")
    results["segment"] = [
        "promotion months" if promo else
        ("promoted SKUs, normal months" if pid in promoted else "never-promoted SKUs")
        for promo, pid in zip(results["on_promotion"], results["product_id"])]
    return results


def evaluation_summary() -> dict | None:
    try:
        return json.loads((DOCS / "assistant_evaluation_summary.json").read_text())
    except (OSError, ValueError):
        return None


class _AskFailed(Exception):
    """Raised inside the cached function so that failures are never cached."""


@st.cache_data(show_spinner=False, ttl=3600)
def cached_ask(question: str) -> assistant.Answer:
    """Repeat questions reuse a successful answer. Errors are not cached, so a fixed key works at once."""
    answer = assistant.ask(question, db_path=DB)
    if answer.error and "unavailable" in answer.error:
        raise _AskFailed(answer.error)
    return answer


def line_chart(wide: pd.DataFrame, y_title: str) -> None:
    """A static line chart (index = month, one column per line). Unlike st.line_chart it does
    not zoom when the page is scrolled over it. Hover shows the values."""
    long = wide.reset_index(names="month").melt("month", var_name="series", value_name="value")
    chart = alt.Chart(long).mark_line(point=True).encode(
        x=alt.X("month:N", title=None),
        y=alt.Y("value:Q", title=y_title, scale=alt.Scale(zero=True)),
        color=alt.Color("series:N", title=None, sort=list(wide.columns),
                        legend=alt.Legend(orient="bottom", labelLimit=320)),
        tooltip=["month", "series", alt.Tooltip("value:Q", format=",.0f")],
    ).properties(height=340)
    st.altair_chart(chart, width="stretch")


def gbp(x: float) -> str:
    return f"£{x / 1e6:,.2f}m" if abs(x) >= 1e6 else f"£{x:,.0f}"


# ------------------------------------------------------------------ page
st.set_page_config(page_title="Commercial Decision Engine", page_icon="📈", layout="wide")
st.title("📈 Commercial Decision Engine")
st.caption(f"{COMPANY}: 30 drinks products, 3 regions, monthly sales 2023 to 2025. "
           "All data is synthetic, generated from a fixed seed. No real company data is used.")

tab_dash, tab_forecast, tab_ask = st.tabs(["Dashboard", "Forecast", "Ask the data"])

# ------------------------------------------------------------------ 1. dashboard
with tab_dash:
    sales = load_sales()
    sales["year"] = sales["month"].str[:4]
    year = st.radio("Year", ["2025", "2024", "2023"], horizontal=True)
    this = sales[sales["year"] == year]
    prev = sales[sales["year"] == str(int(year) - 1)]

    def growth(now: float, before: float) -> str | None:
        return f"{(now / before - 1) * 100:+.1f}% vs {int(year) - 1}" if before else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Revenue", gbp(this["revenue_gbp"].sum()),
              growth(this["revenue_gbp"].sum(), prev["revenue_gbp"].sum()))
    c2.metric("Volume (cases)", f"{this['volume_cases'].sum():,}",
              growth(this["volume_cases"].sum(), prev["volume_cases"].sum()))
    promo_share = this.loc[this["on_promotion"] == 1, "revenue_gbp"].sum() / this["revenue_gbp"].sum()
    c3.metric("Revenue sold on promotion", f"{promo_share:.1%}")

    st.subheader("Monthly revenue by category")
    line_chart(this.pivot_table(index="month", columns="category", values="revenue_gbp",
                                aggfunc="sum"), "Revenue (GBP)")

    st.subheader("Regions")
    by_region = this.groupby("region")[["revenue_gbp", "volume_cases"]].sum()
    if not prev.empty:
        before = prev.groupby("region")["volume_cases"].sum()
        by_region["volume growth"] = (by_region["volume_cases"] / before - 1) * 100
    by_region = by_region.rename(columns={"revenue_gbp": "Revenue", "volume_cases": "Volume (cases)",
                                          "volume growth": "Volume growth"})
    st.dataframe(by_region.sort_values("Revenue", ascending=False).style.format(
        {"Revenue": "£{:,.0f}", "Volume (cases)": "{:,}", "Volume growth": "{:+.1f}%"}),
        width="stretch")
    if year == "2025":
        st.warning(
            "**Read the South's growth with care.** Part of it is a recovery, not new demand: "
            "a supply problem cut South Carbonated volume in July 2024, so 2024 is a low base. "
            "Ask *which region grew fastest* and the correct SQL still gives a misleading answer.")

# ------------------------------------------------------------------ 2. forecast
with tab_forecast:
    st.markdown(
        "Each month of 2025 is forecast using **only the months before it** (walk-forward), "
        "with three simple rules and one machine-learning model. Error is WMAPE: total "
        "absolute error as a % of actual volume. **Lower is better.**")
    with st.spinner("Running the walk-forward forecasts (about 3 seconds)..."):
        results = forecast_results()

    table = pd.concat([score(results).assign(segment="All forecasts"),
                       score(results, "segment").replace({"segment": SEGMENT_NAMES})])
    shown = table.rename(columns={f"{m}_wmape": METHOD_NAMES[m] for m in METHOD_NAMES} |
                         {"ml_gain_pts": "ML gain vs best rule (pts)", "rows": "forecasts"})
    error_cols = [METHOD_NAMES[m] for m in METHOD_NAMES] + ["ML gain vs best rule (pts)"]
    st.dataframe(shown.set_index("segment").style.format("{:.1f}", subset=error_cols),
                 width="stretch")
    st.info(
        "**Decision rule:** use the model where it has information the rules cannot use. Here "
        "that is the promotion calendar, so the gain is largest in promotion months. Elsewhere, "
        "require evidence on your own data first. On real distributor data in my MSc "
        "dissertation, ML did **not** beat the simple rules: synthetic results like these "
        "cannot prove real-world value.")

    st.subheader("One product in one region")
    c1, c2 = st.columns(2)
    products = sorted(sales["product"].unique())
    # Start on the product with the most promotions in 2025, where the methods differ most.
    most_promoted = results.groupby("product")["on_promotion"].sum().idxmax()
    product = c1.selectbox("Product", products, index=products.index(most_promoted))
    region = c2.selectbox("Region", ["North", "Central", "South"])
    one = results[(results["product"] == product) & (results["region"] == region)]
    if one.empty:
        st.info("No forecasts for this product and region: it needs a full year of history first.")
    else:
        line_chart(one.set_index("month")[["volume_cases", "naive", "growth_12m", "xgboost"]]
                   .rename(columns={"volume_cases": "Actual"} | METHOD_NAMES), "Cases")
        promo_months = one.loc[one["on_promotion"] == 1, "month"].tolist()
        st.caption("Promotion months: " + (", ".join(promo_months) if promo_months else "none") + ".")
    st.caption("Recomputed live from the database each time the app starts. "
               "Stress tests on messier data: docs/when_does_ml_win.csv.")

# ------------------------------------------------------------------ 3. ask the data
with tab_ask:
    st.markdown(
        "Ask a question in plain English. The AI writes **SQL**, our code checks it and runs it "
        "on a **read-only** copy of the database, and every number below comes from the "
        "database, not from the AI. The SQL is always shown so the answer can be checked.")
    summary = evaluation_summary()
    if summary:
        full = summary["accuracy_pct"].get("full", {})
        st.caption(
            f"Tested on {summary['questions']} hand-checked questions x {summary['repeats']} runs: "
            f"{full.get('ALL', 0):.1f}% correct overall, {full.get('fresh', 0):.1f}% on questions "
            "written after the last change. It refused every hostile request in testing. "
            "Details: docs/evaluation_log.md.")

    example = st.selectbox("Try an example, or type your own below", ["", *EXAMPLES])
    question = st.text_input("Your question", value=example, max_chars=300)
    asked = st.session_state.setdefault("questions_asked", 0)
    if st.button("Ask", type="primary",
                 disabled=not question.strip() or asked >= MAX_QUESTIONS_PER_SESSION):
        st.session_state["questions_asked"] = asked + 1
        with st.spinner("Writing and checking the query..."):
            try:
                st.session_state["answer"] = cached_ask(question.strip())
            except _AskFailed as exc:
                st.session_state["answer"] = assistant.Answer(question=question, error=str(exc))
    left = MAX_QUESTIONS_PER_SESSION - st.session_state["questions_asked"]  # after this click
    st.caption(f"{max(left, 0)} of {MAX_QUESTIONS_PER_SESSION} questions left in this session "
               "(a limit to keep the cost of the public demo down).")

    answer = st.session_state.get("answer")
    if answer is not None:
        st.markdown(f"**Q: {answer.question}**")
        if answer.refused:
            st.warning(f"**The assistant declined:** {answer.refused}")
        elif answer.error:
            st.error(answer.error)
        else:
            if answer.assumption:
                st.info(f"**Assumption made:** {answer.assumption}  \n"
                        "This is the AI's description of its query. Check it against the SQL below.")
            st.dataframe(answer.data, hide_index=True, width="stretch")
            if len(answer.data) == assistant.MAX_ROWS:
                st.caption(f"Showing the first {assistant.MAX_ROWS} rows only.")
        if answer.sql:
            st.code(answer.sql, language="sql")
