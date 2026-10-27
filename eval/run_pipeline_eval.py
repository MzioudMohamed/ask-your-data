"""Run the pipeline on the intent gold set and score it.

By default only the dev questions are used: they are the ones the prompt and thresholds may be tuned on.
The test questions are frozen. They need the --final flag, and should only be run for the final numbers.
"""
import argparse
import json

from askdata import config, pipeline
from askdata.schemas import Answer
from askdata.sql.executor import run_intent
from eval.check_intent_gold import load_gold, reference_intent
from eval.scoring import score_question, summarize


def reference_hashes(questions):
    """Result hash of the reference intent of every answerable question."""
    return {q["id"]: run_intent(reference_intent(q))[1].result_hash for q in questions if q["status"] == "answered"}


def run(model, questions, hashes, use_rag=True):
    rows = []
    for q in questions:
        try:
            answer = pipeline.answer_question(q["text"], model=model, use_rag=use_rag)
        except Exception as exc:  # a crash is a failure, not a reason to stop the evaluation
            answer = Answer(question=q["text"], status="error", errors=[f"crash: {type(exc).__name__}: {str(exc)[:150]}"])
        row = score_question(q, answer, hashes.get(q["id"]))
        rows.append(row)
        mark = "ok  " if row["correct"] else "FAIL"
        print(f"  {q['id']} {mark} {row['status']:<19}{row['total_ms'] / 1000:5.1f}s  {q['text'][:60]}", flush=True)
        if not row["correct"]:
            if row["expected_status"] != row["status"]:
                print(f"         expected status {row['expected_status']}, got {row['status']}")
            for field, (expected, got) in row["differences"].items():
                print(f"         {field}: expected {expected!r}, got {got!r}")
            if row["cite_ok"] is False:
                print(f"         expected citation {q['cites']}")
            if row["error"]:
                print(f"         error: {row['error'][:200]}")
    return rows


def print_summary(model, s):
    print(f"\n--- {model} ---")
    print(f"correct overall        {s['correct']}/{s['questions']} ({s['correct_rate']:.0%})")
    print(f"answerable questions   {s['answerable']}: same result as the reference {s['result_match']}, "
          f"exact intent {s['intent_exact']}, valid intent {s['intent_valid']}")
    print(f"not answerable         {s['not_answerable']}: answered anyway (false answers) {s['false_answers']}")
    print(f"answerable but not answered: {s['missed_answers']}")
    print("by expected status    ", ", ".join(f"{k} {a}/{b}" for k, (a, b) in s["by_status"].items()))
    print("by language           ", ", ".join(f"{k} {a}/{b}" for k, (a, b) in s["by_lang"].items()),
          f"| hard {s['hard'][0]}/{s['hard'][1]}")
    print(f"median time            {s['median_s']:.1f} s per question ({s['median_llm_s']:.1f} s in the model when used)")


def main():
    parser = argparse.ArgumentParser(description="Evaluate the baseline pipeline on the intent gold set.")
    parser.add_argument("--models", nargs="+", default=[config.LLM_MODEL])
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    parser.add_argument("--final", action="store_true", help="required to touch the frozen test questions")
    parser.add_argument("--no-rag", action="store_true", help="do not give the retrieved definitions to the model")
    parser.add_argument("--only", nargs="+", help="run only these question ids")
    parser.add_argument("--tag", default="baseline", help="name of the system, used in the result file name")
    args = parser.parse_args()

    if args.split != "dev" and not args.final:
        parser.error("the test questions are frozen: add --final to run them (only for the final numbers)")

    questions = [q for q in load_gold() if args.split == "all" or q["split"] == args.split]
    if args.only:
        questions = [q for q in questions if q["id"] in args.only]
    hashes = reference_hashes(questions)

    results = {}
    for model in args.models:
        print(f"\n=== {model} | {args.split} | rag={'off' if args.no_rag else 'on'} | {len(questions)} questions ===")
        rows = run(model, questions, hashes, use_rag=not args.no_rag)
        summary = summarize(rows)
        print_summary(model, summary)
        results[model] = {"summary": summary, "rows": rows}

    out = config.PROJECT_ROOT / "eval" / "results" / f"{args.tag}_{args.split}{'_norag' if args.no_rag else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nDetails saved to {out.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()