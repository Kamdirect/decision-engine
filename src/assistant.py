"""'Ask your data': a plain-English question becomes SQL, which runs read-only against the database.

Trust design:
  - The language model never sees the data. It sees the schema and five worked examples,
    and writes SQL. Our code runs the SQL, so every number shown comes from the database.
  - The SQL is always shown to the user, so the answer can be checked.
  - Guardrails in code, not just in the prompt: one statement only, SELECT/WITH only,
    no write or admin keywords, a read-only connection, a row cap and a time limit.
  - The model answers through one of two tools: run_query (SQL, plus any assumption it made)
    or cannot_answer. A refusal is a correct answer, not a failure.
  - Any assumption is shown to the user next to the answer.
"""

from __future__ import annotations

import os
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

DB_PATH = Path("data/sales.db")
MODEL = "claude-haiku-5-5"
MAX_ROWS = 1000
TIME_LIMIT_S = 5.0

SCHEMA = """SQLite database for Meridian Drinks Co. (fictional), monthly sales 2023-01 to 2025-12.

regions(region_id INTEGER PRIMARY KEY, region_name TEXT)  -- North, Central, South
products(product_id INTEGER PRIMARY KEY, product_name TEXT, category TEXT,
         list_price_gbp REAL, launch_month TEXT, delist_after TEXT)
  -- category is one of: Carbonated, Water, Juice, Energy
  -- list_price_gbp is the price per case before any promotion discount
  -- launch_month is the first month on sale; delist_after is the last month on sale (NULL if still listed)
promotions(month TEXT, region_id INTEGER, product_id INTEGER, discount_pct INTEGER, planned_uplift REAL)
  -- the planned promotion calendar; one row per promoted product-region-month
sales(month TEXT, region_id INTEGER, product_id INTEGER, volume_cases INTEGER,
      revenue_gbp REAL, on_promotion INTEGER)
  -- one row per month x region x product on sale; on_promotion is 1 or 0

Notes:
- month is TEXT formatted 'YYYY-MM'. A year is month LIKE '2025-%'. A quarter, e.g. Q3 2025,
  is month BETWEEN '2025-07' AND '2025-09'.
- "Volume" or "sales volume" means SUM(volume_cases). "Sales" or "revenue" means SUM(revenue_gbp).
- Growth between two periods is (later - earlier) * 100.0 / earlier.
- There is no data on costs, profit, margins, customers, stores, competitors or weather."""

EXAMPLES = [
    ("What was total revenue in 2024?",
     "SELECT ROUND(SUM(revenue_gbp), 2) AS revenue_2024 FROM sales WHERE month LIKE '2024-%';"),
    ("Which region sold the most cases in 2025?",
     "SELECT r.region_name, SUM(s.volume_cases) AS cases\nFROM sales s JOIN regions r USING (region_id)\n"
     "WHERE s.month LIKE '2025-%'\nGROUP BY r.region_name ORDER BY cases DESC LIMIT 1;"),
    ("Top 3 products by revenue in Q2 2025",
     "SELECT p.product_name, ROUND(SUM(s.revenue_gbp), 2) AS revenue\n"
     "FROM sales s JOIN products p USING (product_id)\n"
     "WHERE s.month BETWEEN '2025-04' AND '2025-06'\n"
     "GROUP BY p.product_name ORDER BY revenue DESC LIMIT 3;"),
    ("How did Water volume change from 2024 to 2025, in percent?",
     "WITH y AS (\n  SELECT substr(s.month, 1, 4) AS yr, SUM(s.volume_cases) AS cases\n"
     "  FROM sales s JOIN products p USING (product_id)\n"
     "  WHERE p.category = 'Water' AND substr(s.month, 1, 4) IN ('2024', '2025')\n"
     "  GROUP BY yr\n)\nSELECT ROUND((MAX(CASE WHEN yr = '2025' THEN cases END)\n"
     "             - MAX(CASE WHEN yr = '2024' THEN cases END)) * 100.0\n"
     "             / MAX(CASE WHEN yr = '2024' THEN cases END), 1) AS growth_pct\nFROM y;"),
    ("What was our profit margin on Cola last year?",
     "CANNOT_ANSWER: the database has prices and revenue but no costs, so profit cannot be calculated."),
]

# Output rules, shared by every prompt version so that prompt comparisons are fair.
#
# History (each change was made because an evaluation run showed a problem):
#  run 2: on questions that need interpreting ("last three months", "every month") the model
#         wrote a sentence before correct SQL, and the guardrail (correctly) refused to run
#         prose. 5 of 105 attempts were lost this way.
#  run 3: asking in the prompt for "SQL only, assumption as a comment" did not fix it: the
#         holdout questions still failed. A prompt instruction is a request, not a guarantee.
#  now:   the model must answer by calling one of two TOOLS, so the SQL and the assumption
#         arrive in separate fields. Prose cannot end up in the SQL field by accident.
TOOLS = [
    {"name": "run_query",
     "description": "Answer the question with one read-only SQLite query.",
     "input_schema": {"type": "object", "properties": {
         "sql": {"type": "string",
                 "description": "Exactly one SELECT or WITH ... SELECT statement. SQL only, no prose."},
         "assumption": {"type": "string",
                        "description": "One sentence on how you read an ambiguous question "
                                       "(e.g. which months 'recent' means). Empty if none was needed."}},
         "required": ["sql"]}},
    {"name": "cannot_answer",
     "description": "Use when the data cannot answer the question, or when the request is unsafe, "
                    "would change data, or would give a misleading number.",
     "input_schema": {"type": "object", "properties": {
         "reason": {"type": "string", "description": "One sentence for the user."}},
         "required": ["reason"]}},
]

FORMAT_RULES = """Rules:
- Always reply by calling exactly one tool:
  run_query, with one SELECT or WITH ... SELECT statement, and an assumption if the question
  needed interpreting (for example "recent", "last three months", "today"); or
  cannot_answer, if the data cannot answer the question or you will not write the query."""

SYSTEM_PROMPT = f"""You translate business questions into one SQLite query.

{SCHEMA}

{FORMAT_RULES}
- Use only the tables and columns above. Give result columns clear names.
- Round money to 2 decimals and percentages to 1 decimal.

Examples (SQL is what goes in run_query; CANNOT_ANSWER means call cannot_answer):
""" + "\n\n".join(f"Question: {q}\n{a}" for q, a in EXAMPLES)

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|vacuum|reindex|"
    r"truncate|grant|load_extension)\b",
    re.IGNORECASE,
)


class UnsafeSQL(ValueError):
    """The generated SQL failed a guardrail and was not run."""


@dataclass
class Answer:
    question: str
    sql: str = ""
    data: pd.DataFrame | None = None
    assumption: str | None = None  # how the model read an ambiguous question, shown to the user
    refused: str | None = None   # the model's reason, when it says the data cannot answer
    error: str | None = None     # anything that went wrong; the user sees this, not a guess


def clean_sql(text: str) -> str:
    """Strip markdown fences and surrounding whitespace from the model's reply."""
    text = text.strip()
    fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return (fenced.group(1) if fenced else text).strip()


def assumptions(sql: str) -> str | None:
    """The '-- Assumption:' comment lines the model wrote, joined, or None."""
    found = re.findall(r"^\s*--\s*assumption:\s*(.+)$", sql, re.IGNORECASE | re.MULTILINE)
    return " ".join(a.strip() for a in found) or None


def check_sql(sql: str) -> str:
    """Guardrails. Returns the SQL without a trailing semicolon, or raises UnsafeSQL."""
    body = re.sub(r"--[^\n]*", "", sql).strip().rstrip(";").strip()
    if not body:
        raise UnsafeSQL("empty query")
    if ";" in body:
        raise UnsafeSQL("more than one statement")
    if not re.match(r"^(select|with)\b", body, re.IGNORECASE):
        raise UnsafeSQL("only SELECT queries are allowed")
    hit = _FORBIDDEN.search(body)
    if hit:
        raise UnsafeSQL(f"forbidden keyword: {hit.group(0).upper()}")
    return body


def run_sql(sql: str, db_path: Path = DB_PATH) -> pd.DataFrame:
    """Run a checked query on a read-only connection, with a row cap and a time limit."""
    body = check_sql(sql)
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as con:
        con.execute("PRAGMA query_only = ON")
        deadline = time.monotonic() + TIME_LIMIT_S
        con.set_progress_handler(lambda: int(time.monotonic() > deadline), 10_000)
        try:
            return pd.read_sql(f"SELECT * FROM ({body}) LIMIT {MAX_ROWS}", con)
        except Exception as exc:
            if time.monotonic() > deadline:
                raise UnsafeSQL(f"query took longer than {TIME_LIMIT_S:.0f} seconds") from exc
            raise


def _default_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic

    return anthropic.Anthropic(api_key=key, timeout=30, max_retries=2)


def _reply_from_tool(block) -> str:
    """Turn a tool call into the same text form the rest of the code understands."""
    data = block.input or {}
    if block.name == "cannot_answer":
        return f"CANNOT_ANSWER: {data.get('reason') or 'no reason given'}"
    assumption = " ".join(str(data.get("assumption") or "").split())
    sql = str(data.get("sql") or "")
    return f"-- Assumption: {assumption}\n{sql}" if assumption else sql


def generate_sql(question: str, client, model: str = MODEL, system: str = SYSTEM_PROMPT) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=1000,
        thinking={"type": "disabled"},  # see Project 1: thinking can use the whole token budget
        system=system,
        tools=TOOLS,
        tool_choice={"type": "any"},    # must call a tool: no free-text replies
        messages=[{"role": "user", "content": f"Question: {question}"}],
    )
    for block in response.content:
        if getattr(block, "type", "") == "tool_use":
            return _reply_from_tool(block)
    # No tool call (only possible with fake clients in tests): fall back to the text.
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")


def ask(question: str, client=None, db_path: Path = DB_PATH, model: str = MODEL,
        system: str = SYSTEM_PROMPT) -> Answer:
    """Question in, checked answer out. Never raises: problems are reported in Answer.error."""
    answer = Answer(question=question)
    client = client or _default_client()
    if client is None:
        answer.error = "The assistant is unavailable: no API key is configured."
        return answer
    try:
        reply = clean_sql(generate_sql(question, client, model, system))
    except Exception as exc:
        answer.error = f"The assistant is unavailable: {type(exc).__name__}."
        return answer
    if reply.upper().startswith("CANNOT_ANSWER"):
        answer.refused = reply.split(":", 1)[1].strip() if ":" in reply else "no reason given"
        return answer
    answer.sql = reply
    answer.assumption = assumptions(reply)
    try:
        answer.data = run_sql(reply, db_path)
    except UnsafeSQL as exc:
        answer.error = f"The generated query was blocked ({exc}). I can't answer that reliably."
    except Exception as exc:
        answer.error = f"The generated query failed ({type(exc).__name__}). I can't answer that reliably."
    else:
        if answer.data.empty:
            answer.error = "The query returned no rows. I can't answer that reliably."
    return answer
