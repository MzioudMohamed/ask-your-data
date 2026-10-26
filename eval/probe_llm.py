"""Quick check of candidate language models: speed, valid JSON, and a first look at accuracy.

For each model: one warm-up call (loads the model), then 6 questions. The question is sent with the closest
glossary entries, the model must answer with an Intent JSON, and a few expected fields are compared.
This is a probe, not the final evaluation: the 6 questions only show whether a model is usable on this machine.
"""
import argparse
import json
import statistics
import time

from pydantic import ValidationError

from askdata import config
from askdata.llm import chat_json
from askdata.prompts import build_intent_messages
from askdata.rag.retrieve import retrieve
from askdata.schemas import Intent

DEFAULT_MODELS = ["llama3.2:3b", "qwen3:4b", "gemma3:4b"]

PROBES = [
    ("Quel est le chiffre d'affaires par mois en 2017 ?",
     {"metrics": ["revenue"], "time_grain": "month", "date_from": "2017-01-01", "date_to": "2017-12-31"}),
    ("Top 5 states by number of orders",
     {"metrics": ["orders_count"], "dimensions": ["customer_state"], "top_k": 5}),
    ("Quelle part des livraisons arrive en retard, par état ?",
     {"metrics": ["late_delivery_rate"], "dimensions": ["customer_state"]}),
    ("Average review score per year",
     {"metrics": ["average_review_score"], "time_grain": "year"}),
    ("Taux de réachat à 90 jours par cohorte mensuelle",
     {"metrics": ["repurchase_rate"], "window_days": 90, "time_grain": "month"}),
    ("Revenue by product category for customers in SP in 2018",
     {"metrics": ["revenue"], "dimensions": ["product_category"], "date_from": "2018-01-01",
      "date_to": "2018-12-31", "filters": [{"dimension": "customer_state", "op": "in", "values": ["SP"]}]}),
]


def score(intent_dict, expected):
    """(matching fields, expected fields): only the fields listed in expected are compared."""
    matched = sum(1 for key, value in expected.items() if intent_dict.get(key) == value)
    return matched, len(expected)


def probe_model(model, hits_by_question):
    chat_json([{"role": "user", "content": "Reply with the JSON {}"}], {"type": "object"}, model=model, max_tokens=5)
    rows = []
    for question, expected in PROBES:
        messages = build_intent_messages(question, hits_by_question[question])
        started = time.perf_counter()
        error, intent_dict = None, {}
        try:
            text, stats = chat_json(messages, Intent.model_json_schema(), model=model)
            try:
                raw = json.loads(text)
                json_ok = True
            except json.JSONDecodeError as exc:
                raw, json_ok, error = {}, False, f"invalid JSON: {exc.msg}"
            schema_ok = False
            if json_ok:
                try:
                    intent_dict = Intent.model_validate(raw).model_dump(mode="json")
                    schema_ok = True
                except ValidationError as exc:
                    error = "schema: " + exc.errors()[0]["msg"]
                    intent_dict = raw
        except Exception as exc:  # network or Ollama error
            stats, json_ok, schema_ok, error = {}, False, False, f"{type(exc).__name__}: {str(exc)[:80]}"
        matched, total = score(intent_dict, expected)
        rows.append({
            "question": question, "wall_s": time.perf_counter() - started, "json_ok": json_ok,
            "schema_ok": schema_ok, "matched": matched, "total": total, "error": error, "stats": stats,
            "intent": intent_dict,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="Probe candidate language models on this machine.")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    args = parser.parse_args()

    hits = {q: retrieve(q, k=3) for q, _ in PROBES}
    summary = []
    for model in args.models:
        print(f"\n=== {model} ===", flush=True)
        rows = probe_model(model, hits)
        for r in rows:
            tps = r["stats"].get("gen_tokens_per_s", 0)
            print(f"  {r['wall_s']:5.1f}s  {tps:5.1f} tok/s  json={'ok' if r['json_ok'] else 'NO'} "
                  f"intent={'ok' if r['schema_ok'] else 'NO'}  fields {r['matched']}/{r['total']}  {r['question'][:45]}")
            if r["error"]:
                print(f"         -> {r['error']}")
        ok = [r for r in rows if r["stats"]]
        summary.append({
            "model": model,
            "median_s": statistics.median(r["wall_s"] for r in rows),
            "median_tps": statistics.median(r["stats"].get("gen_tokens_per_s", 0) for r in ok) if ok else 0,
            "prompt_tokens": ok[0]["stats"]["prompt_tokens"] if ok else 0,
            "json_ok": sum(r["json_ok"] for r in rows) / len(rows),
            "schema_ok": sum(r["schema_ok"] for r in rows) / len(rows),
            "fields": sum(r["matched"] for r in rows) / sum(r["total"] for r in rows),
        })

    print("\nmodel               s/question  tok/s  prompt tok  json  intent  fields")
    for s in summary:
        print(f"{s['model']:<20}{s['median_s']:>9.1f}{s['median_tps']:>8.1f}{s['prompt_tokens']:>12}"
              f"{s['json_ok']:>6.0%}{s['schema_ok']:>8.0%}{s['fields']:>8.0%}")

    out = config.PROJECT_ROOT / "eval" / "results" / "llm_probe_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()