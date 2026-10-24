"""Run a .sql file against the database and print the result.

Run from the project root:  python -m scripts.run_sql queries/category_2025.sql
"""

import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pandas as pd

DB_PATH = Path("data/sales.db")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.run_sql <file.sql>")
    sql = Path(sys.argv[1]).read_text(encoding="utf-8")
    # Open read-only, so a query can never change the data.
    with closing(sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)) as con:
        print(pd.read_sql(sql, con).to_string(index=False))


if __name__ == "__main__":
    main()
