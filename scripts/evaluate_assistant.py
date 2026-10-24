"""Grade the assistant on the 45 hand-checked questions (core, hard, holdout, fresh), with two prompts:
  schema_only  table definitions only (the "before")
  full         + notes on how the data is written + 5 worked examples (the "after")

Uses the live model, so it needs ANTHROPIC_API_KEY in .env. About 270 short calls with the
default 3 repeats: well under GBP 1 on Haiku. Run from the project root:

    python -m scripts.evaluate_assistant
    python -m scripts.evaluate_assistant --repeats 1     (cheaper, quicker)
"""

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from src.assistant import MODEL, SYSTEM_PROMPT
from src.eval_set import QUESTIONS
from src.grading import SCHEMA_ONLY_PROMPT, by_kind, consistency, evaluate, summarise

OUT = Path("docs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    load_dotenv()

    prompts = {"schema_only": SCHEMA_ONLY_PROMPT, "full": SYSTEM_PROMPT}
    print(f"Asking {len(QUESTIONS)} questions x {len(prompts)} prompts x {args.repeats} repeats")
    results = evaluate(QUESTIONS, prompts, repeats=args.repeats)

    if results["detail"].str.contains("assistant is unavailable").all():
        print("\nEvery call failed: is ANTHROPIC_API_KEY in .env, and is there credit? Nothing saved.")
        return

    table = summarise(results)
    table.insert(1, "consistent", consistency(results))
    OUT.mkdir(exist_ok=True)
    results.to_csv(OUT / "assistant_evaluation.csv", index=False)
    (OUT / "assistant_evaluation_summary.json").write_text(json.dumps(
        {"model": MODEL, "questions": len(QUESTIONS), "repeats": args.repeats,
         "accuracy_pct": table.to_dict(orient="index")}, indent=2))

    print("\nAccuracy, % of attempts (consistent = % of questions with the same verdict every run)")
    print(table.to_string())
    print("\nAccuracy by kind of question, %")
    print(by_kind(results).to_string())
    failures = results[~results["correct"] & results["prompt"].eq("full")]
    print(f"\nFailures with the full prompt: {len(failures)} of {int(results['prompt'].eq('full').sum())}")
    for f in failures.drop_duplicates("id").itertuples():
        n = int((results["prompt"].eq("full") & results["id"].eq(f.id) & ~results["correct"]).sum())
        print(f"\n{f.id} [{f.outcome}, wrong in {n} of {args.repeats} runs] {f.question}"
              f"\n  why: {f.detail}\n  sql: {f.sql or '-'}")
    print(f"\nSaved {OUT / 'assistant_evaluation.csv'} and the summary JSON.")


if __name__ == "__main__":
    main()
