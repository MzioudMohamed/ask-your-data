import argparse
import json
import statistics
import time

import yaml

from askdata import config
from askdata.rag.index_glossary import index_glossary
from askdata.rag.retrieve import retrieve

GOLD_PATH = config.PROJECT_ROOT / "eval" / "retrieval_gold.yml"
RESULTS_PATH = config.PROJECT_ROOT / "eval" / "results" / "retrieval_latest.json"
DEFAULT_MODELS = ["qwen3-embedding:0.6b", "bge-m3", "embeddinggemma"]


def load_gold():
    with open(GOLD_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]


def run_model(model, gold):
    """Index the glossary with this model, then run every gold question and time it."""
    index_glossary(model)

    start = time.perf_counter()
    retrieve("warm-up", k=1, model=model)  # the first call loads the model in memory
    cold_ms = (time.perf_counter() - start) * 1000

    results = []
    for q in gold:
        start = time.perf_counter()
        hits = retrieve(q["text"], k=3, model=model)
        ms = (time.perf_counter() - start) * 1000
        ids = [h["entry_id"] for h in hits]
        rank = next((i + 1 for i, entry_id in enumerate(ids) if entry_id in q["expected"]), None)
        results.append({
            "id": q["id"], "lang": q["lang"], "hard": bool(q.get("hard")),
            "in_scope": bool(q["expected"]), "expected": q["expected"],
            "top3": ids, "top1_similarity": hits[0]["similarity"], "rank": rank, "ms": ms,
        })
    return cold_ms, results


def rate(rows, predicate):
    return sum(1 for r in rows if predicate(r)) / len(rows) if rows else float("nan")


def summarize(model, cold_ms, results):
    scoped = [r for r in results if r["in_scope"]]
    out_of_scope = [r for r in results if not r["in_scope"]]
    hit1 = lambda r: r["rank"] == 1
    hit3 = lambda r: r["rank"] is not None

    # Best "answer or refuse" threshold on the top-1 similarity (scales differ between models).
    candidates = sorted({r["top1_similarity"] for r in results})
    best_accuracy, best_threshold = max(
        (sum((r["top1_similarity"] >= t) == r["in_scope"] for r in results) / len(results), t)
        for t in candidates
    )
    return {
        "model": model,
        "hit1": rate(scoped, hit1),
        "hit3": rate(scoped, hit3),
        "mrr3": sum((1 / r["rank"]) if r["rank"] else 0 for r in scoped) / len(scoped),
        "hit1_fr": rate([r for r in scoped if r["lang"] == "fr"], hit1),
        "hit1_en": rate([r for r in scoped if r["lang"] == "en"], hit1),
        "hit1_hard": rate([r for r in scoped if r["hard"]], hit1),
        "median_ms": statistics.median(r["ms"] for r in results),
        "cold_ms": cold_ms,
        "in_scope_min_similarity": min(r["top1_similarity"] for r in scoped),
        "out_of_scope_max_similarity": max(r["top1_similarity"] for r in out_of_scope),
        "threshold": best_threshold,
        "threshold_accuracy": best_accuracy,
    }


def main():
    parser = argparse.ArgumentParser(description="Compare embedding models on the glossary retrieval gold set.")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()

    gold = load_gold()
    summaries, details = [], {}
    for model in args.models:
        print(f"Running {model} ...", flush=True)
        cold_ms, results = run_model(model, gold)
        summaries.append(summarize(model, cold_ms, results))
        details[model] = results

    print()
    print(f"{'model':<24}{'hit@1':>7}{'hit@3':>7}{'MRR@3':>7}{'fr@1':>7}{'en@1':>7}{'hard@1':>8}{'ms/q':>8}{'cold ms':>9}")
    for s in summaries:
        print(f"{s['model']:<24}{s['hit1']:>7.2f}{s['hit3']:>7.2f}{s['mrr3']:>7.2f}{s['hit1_fr']:>7.2f}"
              f"{s['hit1_en']:>7.2f}{s['hit1_hard']:>8.2f}{s['median_ms']:>8.0f}{s['cold_ms']:>9.0f}")

    print()
    print("Answer-or-refuse threshold on the top-1 similarity (all 38 questions):")
    print(f"{'model':<24}{'min in-scope':>14}{'max out-of-scope':>18}{'best threshold':>16}{'accuracy':>10}")
    for s in summaries:
        print(f"{s['model']:<24}{s['in_scope_min_similarity']:>14.3f}{s['out_of_scope_max_similarity']:>18.3f}"
              f"{s['threshold']:>16.3f}{s['threshold_accuracy']:>10.2f}")

    print()
    print("In-scope questions not answered at rank 1:")
    for model in args.models:
        for r in details[model]:
            if r["in_scope"] and r["rank"] != 1:
                print(f"  {model:<22} {r['id']} expected={r['expected']} got={r['top3']}")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"summaries": summaries, "details": details}, f, ensure_ascii=False, indent=2)
    print(f"\nDetails saved to {RESULTS_PATH.relative_to(config.PROJECT_ROOT)}")


if __name__ == "__main__":
    main()