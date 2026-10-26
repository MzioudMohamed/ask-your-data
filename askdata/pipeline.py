"""Baseline pipeline, without agents: question -> glossary search -> intent -> SQL -> result -> answer.

Every step is a plain function call. Routing uses the glossary search only:
  - nothing close in the glossary           -> unsupported (out of scope)
  - the closest entry is an unsupported one  -> unsupported (for example churn)
  - the closest entry is a concept           -> definition, taken from the glossary
  - the closest entry is a metric            -> the language model builds an Intent, which becomes SQL.
The multi-agent version will be measured against this one.
"""
import argparse
import time

from pydantic import ValidationError

from askdata import config, glossary
from askdata.llm import chat_json
from askdata.prompts import build_intent_messages
from askdata.rag.retrieve import retrieve
from askdata.schemas import Answer, Citation, Intent
from askdata.sql.executor import ExecutionError, execute
from askdata.sql.templates import TemplateError, build_plan
from askdata.sql.validator import SQLValidationError

OUT_OF_SCOPE = (
    "I can only answer questions about the e-commerce metrics of the glossary: revenue, orders, basket, "
    "delivery, reviews and repurchase.\n"
    "Je ne peux répondre qu'aux questions sur les métriques du glossaire : chiffre d'affaires, commandes, "
    "panier, livraison, avis et réachat."
)


def _ms(since):
    return round((time.perf_counter() - since) * 1000, 1)


def _citation(entry_id, entry, similarity):
    return Citation(entry_id=entry_id, name=entry["name_en"], model=entry.get("model"),
                    similarity=round(similarity, 3))


def _bilingual(entry):
    return " ".join(entry["definition_en"].split()) + "\n" + " ".join(entry["definition_fr"].split())


def _describe(result, limit=3):
    """Plain description of the result. The language-model narrative will replace it in the agent version."""
    if result.row_count == 0:
        return "No data matches this question."
    lines = []
    for row in result.preview(limit):
        lines.append(", ".join(f"{name} = {value}" for name, value in zip(result.columns, row)))
    more = f" ({result.row_count} rows in total)" if result.row_count > limit else ""
    return "Result" + more + ": " + " | ".join(lines)


def answer_question(question, model=None, k=3, use_rag=True) -> Answer:
    timings = {}
    started = time.perf_counter()

    def finish(**fields):
        timings["total"] = _ms(started)
        return Answer(question=question, timings_ms=timings, **fields)

    step = time.perf_counter()
    hits = retrieve(question, k=k)
    timings["retrieval"] = _ms(step)

    top = hits[0] if hits else None
    if top is None or top["similarity"] < config.MIN_SIMILARITY:
        return finish(status="unsupported", narrative=OUT_OF_SCOPE)
    entry = top["entry"]
    citation = _citation(top["entry_id"], entry, top["similarity"])

    if entry["type"] == "unsupported":
        return finish(status="unsupported", narrative=_bilingual(entry), citations=[citation])
    if entry["type"] == "concept":
        return finish(status="definition", narrative=_bilingual(entry), citations=[citation])

    step = time.perf_counter()
    try:
        text, _ = chat_json(build_intent_messages(question, hits if use_rag else None),
                            Intent.model_json_schema(), model=model)
    except Exception as exc:  # Ollama stopped, model missing...
        timings["llm"] = _ms(step)
        return finish(status="error", errors=[f"language model unavailable: {str(exc)[:200]}"])
    timings["llm"] = _ms(step)

    try:
        intent = Intent.model_validate_json(text)
    except ValidationError as exc:
        details = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])
        return finish(status="error", errors=[f"the model produced an invalid intent ({details})"])
    if intent.needs_clarification:
        return finish(status="needs_clarification", intent=intent,
                      clarification=intent.clarification or "Could you rephrase or give more details?")

    step = time.perf_counter()
    try:
        plan = build_plan(intent)
        result = execute(plan)
    except (TemplateError, SQLValidationError, ExecutionError) as exc:
        timings["sql"] = _ms(step)
        return finish(status="error", intent=intent, errors=[str(exc)[:300]])
    timings["sql"] = _ms(step)

    similarity_by_id = {h["entry_id"]: h["similarity"] for h in hits}
    citations = [
        _citation(m, glossary.metrics()[m], similarity_by_id.get(m, 0.0)) for m in intent.metrics
    ]
    return finish(
        status="answered", intent=intent, sql_plan=plan, columns=result.columns, rows=result.preview(100),
        row_count=result.row_count, result_hash=result.result_hash, narrative=_describe(result),
        citations=citations,
    )


def main():
    parser = argparse.ArgumentParser(description="Ask a question to the baseline pipeline.")
    parser.add_argument("question")
    parser.add_argument("--model", default=config.LLM_MODEL)
    parser.add_argument("--no-rag", action="store_true", help="do not give the retrieved definitions to the model")
    args = parser.parse_args()

    answer = answer_question(args.question, model=args.model, use_rag=not args.no_rag)
    print(f"status: {answer.status}")
    if answer.intent:
        print("intent:", answer.intent.model_dump(mode="json", exclude_defaults=True))
    if answer.sql_plan:
        print(answer.sql_plan.sql)
        print("params:", answer.sql_plan.params)
        print(answer.columns)
        for row in answer.rows[:10]:
            print(row)
    for line in (answer.narrative, answer.clarification, *answer.errors):
        if line:
            print(line)
    if answer.citations:
        print("citations:", ", ".join(f"[{c.entry_id}] {c.similarity}" for c in answer.citations))
    print("timings (ms):", answer.timings_ms)


if __name__ == "__main__":
    main()