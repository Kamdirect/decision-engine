"""Ask the database a question in plain English, from the command line.

Run from the project root (needs ANTHROPIC_API_KEY in .env):
    python -m scripts.ask "Which region grew fastest in 2025?"
"""

import sys

from dotenv import load_dotenv

from src.assistant import ask


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('Usage: python -m scripts.ask "your question"')
    load_dotenv()
    a = ask(sys.argv[1])
    print(f"Question: {a.question}\n")
    if a.refused:
        print(f"Can't answer from this data: {a.refused}")
        return
    if a.sql:
        print(f"SQL:\n{a.sql}\n")
    if a.error:
        print(a.error)
    else:
        print(a.data.to_string(index=False))


if __name__ == "__main__":
    main()
