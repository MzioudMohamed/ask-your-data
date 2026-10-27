"""Scoring rules shared by the evaluation scripts: how an Answer is compared to a gold question."""
import json
import statistics

from askdata.schemas import Intent

IGNORED_FIELDS = {"confidence", "clarification"}


def _canonical(intent_dict):
    """Same intent written the same way: no confidence, sorted lists."""
    data = {k: v for k, v in intent_dict.items() if k not in IGNORED_FIELDS}
    data["metrics"] = sorted(data["metrics"])
    data["dimensions"] = sorted(data["dimensions"])
    data["filters"] = sorted(
        ({"dimension": f["dimension"], "op": f["op"], "values": sorted(f["values"])} for f in data["filters"]),
        key=lambda f: json.dumps(f, sort_keys=True),
    )
    return data


def expected_intent(gold_question):
    return Intent(confidence=1.0, **gold_question["expected"]).model_dump(mode="json")


def intent_differences(expected, got):
    """Fields that differ between the expected and the produced intent: {field: (expected, got)}."""
    expected, got = _canonical(expected), _canonical(got)
    return {k: (expected[k], got.get(k)) for k in expected if expected[k] != got.get(k)}


def score_question(gold_question, answer, expected_hash=None):
    """Compare one Answer to its gold question. Returns a flat dict that is easy to store and aggregate."""
    gold_status = gold_question["status"]
    row = {
        "id": gold_question["id"], "split": gold_question["split"], "lang": gold_question["lang"],
        "hard": bool(gold_question.get("hard")), "expected_status": gold_status, "status": answer.status,
        "status_ok": answer.status == gold_status,
        "intent_valid": answer.intent is not None, "intent_exact": None, "result_match": None,
        "differences": {}, "cite_ok": None, "error": answer.errors[0] if answer.errors else None,
        "total_ms": answer.timings_ms.get("total", 0.0), "llm_ms": answer.timings_ms.get("llm"),
        "intent": answer.intent.model_dump(mode="json", exclude_defaults=True) if answer.intent else None,
        "text": gold_question["text"],
    }
    if gold_status == "answered":
        if answer.intent is not None:
            row["differences"] = intent_differences(expected_intent(gold_question), answer.intent.model_dump(mode="json"))
        row["intent_exact"] = answer.intent is not None and not row["differences"]
        row["result_match"] = answer.status == "answered" and answer.result_hash == expected_hash
        row["correct"] = row["result_match"]
    else:
        cites = gold_question.get("cites")
        if cites:
            row["cite_ok"] = cites in [c.entry_id for c in answer.citations]
        row["correct"] = row["status_ok"] and row["cite_ok"] is not False
    row["false_answer"] = gold_status != "answered" and answer.status == "answered"
    row["missed_answer"] = gold_status == "answered" and answer.status != "answered"
    return row


def _rate(rows, key):
    return sum(1 for r in rows if r[key]) / len(rows) if rows else float("nan")


def summarize(rows):
    answerable = [r for r in rows if r["expected_status"] == "answered"]
    others = [r for r in rows if r["expected_status"] != "answered"]
    times = [r["total_ms"] for r in rows]
    llm_times = [r["llm_ms"] for r in rows if r["llm_ms"]]
    by_status = {}
    for status in sorted({r["expected_status"] for r in rows}):
        group = [r for r in rows if r["expected_status"] == status]
        by_status[status] = (sum(r["correct"] for r in group), len(group))
    return {
        "questions": len(rows),
        "correct": sum(r["correct"] for r in rows),
        "correct_rate": _rate(rows, "correct"),
        "answerable": len(answerable),
        "result_match": sum(1 for r in answerable if r["result_match"]),
        "intent_valid": sum(1 for r in answerable if r["intent_valid"]),
        "intent_exact": sum(1 for r in answerable if r["intent_exact"]),
        "not_answerable": len(others),
        "false_answers": sum(r["false_answer"] for r in others),
        "missed_answers": sum(r["missed_answer"] for r in answerable),
        "by_status": by_status,
        "by_lang": {
            lang: (sum(r["correct"] for r in rows if r["lang"] == lang), sum(1 for r in rows if r["lang"] == lang))
            for lang in sorted({r["lang"] for r in rows})
        },
        "hard": (sum(r["correct"] for r in rows if r["hard"]), sum(1 for r in rows if r["hard"])),
        "median_s": statistics.median(times) / 1000 if times else 0.0,
        "median_llm_s": statistics.median(llm_times) / 1000 if llm_times else 0.0,
    }