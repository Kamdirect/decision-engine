"""Send 15 hostile or misleading requests to the assistant and record which layer stopped each.

Uses the live model (ANTHROPIC_API_KEY in .env). About 45 short calls: a few pence.
Run from the project root:   python -m scripts.evaluate_guardrails
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from src.assistant import MODEL
from src.guardrail_set import GUARDRAIL_SET
from src.guardrails_eval import evaluate_guardrails, layer_table

OUT = Path("docs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    load_dotenv()

    print(f"Sending {len(GUARDRAIL_SET)} hostile requests x {args.repeats} repeats")
    results, unchanged = evaluate_guardrails(GUARDRAIL_SET, repeats=args.repeats)
    if results["outcome"].eq("not_run").all():
        print("\nEvery call failed: is ANTHROPIC_API_KEY in .env, and is there credit? Nothing saved.")
        return

    OUT.mkdir(exist_ok=True)
    results.to_csv(OUT / "guardrail_evaluation.csv", index=False)
    table = layer_table(results)
    (OUT / "guardrail_evaluation_summary.json").write_text(json.dumps(
        {"model": MODEL, "requests": len(GUARDRAIL_SET), "repeats": args.repeats,
         "safe_pct": float(table.loc["total", "safe_pct"]), "database_unchanged": unchanged,
         "outcomes": results["outcome"].value_counts().to_dict()}, indent=2))

    print("\nWhich layer stopped each attempt")
    print(table.to_string())
    print(f"\nDatabase file unchanged (SHA-256 before = after): {unchanged}")
    unsafe = results[~results["safe"]]
    print(f"Unsafe attempts: {len(unsafe)} of {len(results)}")
    for u in unsafe.drop_duplicates("id").itertuples():
        print(f"\n{u.id} [{u.kind}] {u.request}\n  sql: {u.sql}\n  result: {u.detail}")
    print(f"\nSaved {OUT / 'guardrail_evaluation.csv'} and the summary JSON.")


if __name__ == "__main__":
    main()
