import json

import pytest

from askdata import glossary, pipeline
from eval.check_intent_gold import load_gold
from eval.run_pipeline_eval import reference_hashes, run
from eval.scoring import expected_intent, intent_differences, summarize

GOLD = load_gold()
BY_TEXT = {q["text"]: q for q in GOLD}
BY_ID = {q["id"]: q for q in GOLD}
ENTRIES = {e["id"]: e for e in glossary.load_entries()}
HASHES = reference_hashes(GOLD)


def default_route(q):
    """Where a perfect glossary search would send the question: (closest entry, similarity)."""
    if q["status"] == "answered":
        return q["expected"]["metrics"][0], 0.6
    if q.get("cites"):
        return q["cites"], 0.65
    if q["status"] == "needs_clarification":
        return "revenue", 0.5
    return "revenue", 0.2  # out of scope: nothing close


def default_reply(q):
    if q["status"] == "answered":
        return {**q["expected"], "confidence": 0.9}
    return {"metrics": ["revenue"], "confidence": 0.2, "clarification": "Which period?"}


@pytest.fixture
def evaluate(monkeypatch):
    """Runs the evaluation with a stand-in for the glossary search and the language model.
    overrides: {question id: {"route": (entry id, similarity), "reply": intent dict}}."""
    def go(overrides=None, questions=GOLD):
        overrides = overrides or {}

        def fake_retrieve(question, k=3):
            q = BY_TEXT[question]
            entry_id, similarity = overrides.get(q["id"], {}).get("route", default_route(q))
            return [{"entry_id": entry_id, "similarity": similarity, "entry": ENTRIES[entry_id]}]

        def fake_chat(messages, schema, model=None, **kwargs):
            question = messages[-1]["content"].split("Question: ")[-1].rsplit("\nJSON:", 1)[0]
            q = BY_TEXT[question]
            return json.dumps(overrides.get(q["id"], {}).get("reply", default_reply(q))), {}

        monkeypatch.setattr(pipeline, "retrieve", fake_retrieve)
        monkeypatch.setattr(pipeline, "chat_json", fake_chat)
        rows = run("fake-model", questions, HASHES)
        return rows, summarize(rows)
    return go


# ---------- intent comparison (no database needed) ----------

def test_expected_intent_fills_the_default_fields():
    intent = expected_intent(BY_ID["i02"])
    assert intent["metrics"] == ["revenue"] and intent["time_grain"] == "year" and intent["dimensions"] == []


def test_confidence_and_the_order_of_lists_do_not_matter():
    a = expected_intent(BY_ID["i27"])
    b = {**a, "metrics": list(reversed(a["metrics"])), "confidence": 0.1, "clarification": "x"}
    assert intent_differences(a, b) == {}


def test_filter_values_are_compared_without_order():
    base = expected_intent(BY_ID["i09"])
    shuffled = {**base, "filters": [{**base["filters"][0], "values": list(reversed(base["filters"][0]["values"]))}]}
    assert intent_differences(base, shuffled) == {}


def test_differences_name_the_fields_that_differ():
    a = expected_intent(BY_ID["i02"])
    b = {**a, "time_grain": "month", "dimensions": ["customer_state"]}
    assert intent_differences(a, b) == {"time_grain": ("year", "month"), "dimensions": ([], ["customer_state"])}


# ---------- scoring a whole run ----------

def test_a_perfect_system_scores_everything(evaluate):
    rows, summary = evaluate()
    assert summary["correct"] == summary["questions"] == 45
    assert summary["false_answers"] == 0 and summary["missed_answers"] == 0
    assert summary["result_match"] == summary["answerable"] == 31


def test_a_wrong_time_grain_is_a_wrong_result(evaluate):
    reply = {**BY_ID["i02"]["expected"], "time_grain": "month", "confidence": 0.9}
    rows, summary = evaluate({"i02": {"reply": reply}})
    row = next(r for r in rows if r["id"] == "i02")
    assert row["result_match"] is False and row["intent_exact"] is False
    assert row["differences"] == {"time_grain": ("year", "month")}
    assert summary["correct"] == 44


def test_an_out_of_scope_question_that_gets_an_answer_is_a_false_answer(evaluate):
    weather = BY_ID["i39"]
    rows, summary = evaluate({"i39": {"route": ("delivery_time", 0.56), "reply": {"metrics": ["delivery_time"], "confidence": 0.9}}})
    row = next(r for r in rows if r["id"] == weather["id"])
    assert row["false_answer"] is True and row["correct"] is False
    assert summary["false_answers"] == 1


def test_an_answerable_question_that_is_refused_is_a_missed_answer(evaluate):
    rows, summary = evaluate({"i01": {"route": ("revenue", 0.2)}})
    row = next(r for r in rows if r["id"] == "i01")
    assert row["missed_answer"] is True and row["status"] == "unsupported" and row["correct"] is False
    assert summary["missed_answers"] == 1


def test_a_definition_must_cite_the_right_entry(evaluate):
    rows, summary = evaluate({"i33": {"route": ("valid_order", 0.65)}})
    row = next(r for r in rows if r["id"] == "i33")
    assert row["status_ok"] is True and row["cite_ok"] is False and row["correct"] is False


def test_the_clarification_questions_are_scored_on_status(evaluate):
    rows, _ = evaluate()
    assert {r["status"] for r in rows if r["expected_status"] == "needs_clarification"} == {"needs_clarification"}


def test_the_summary_breaks_results_down(evaluate):
    _, summary = evaluate()
    assert summary["by_status"]["answered"] == (31, 31)
    assert set(summary["by_lang"]) == {"fr", "en"} and summary["hard"] == (10, 10)