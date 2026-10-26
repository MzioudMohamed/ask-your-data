import json

import pytest

from askdata import glossary, pipeline
from askdata.schemas import SQLPlan


def hit(entry_id, similarity=0.6):
    entry = next(e for e in glossary.load_entries() if e["id"] == entry_id)
    return {"entry_id": entry_id, "similarity": similarity, "entry": entry}


class FakeLLM:
    """Stands in for Ollama: returns a canned answer and remembers what it was asked."""

    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, messages, schema, model=None, **kwargs):
        self.calls.append(messages)
        if self.error:
            raise self.error
        return (self.reply if isinstance(self.reply, str) else json.dumps(self.reply)), {}


@pytest.fixture
def ask(monkeypatch):
    def run(hits, llm=None, question="a question", **kwargs):
        llm = llm or FakeLLM(error=AssertionError("the language model must not be called"))
        monkeypatch.setattr(pipeline, "retrieve", lambda q, k=3: hits)
        monkeypatch.setattr(pipeline, "chat_json", llm)
        return pipeline.answer_question(question, **kwargs), llm
    return run


REVENUE_2017 = {"metrics": ["revenue"], "time_grain": "month", "date_from": "2017-01-01", "date_to": "2017-12-31",
                "confidence": 0.9}


def test_a_metric_question_is_answered_with_data_and_citations(ask):
    answer, llm = ask([hit("revenue")], FakeLLM(REVENUE_2017))
    assert answer.status == "answered"
    assert answer.columns == ["period", "revenue"] and answer.row_count > 0
    assert answer.citations[0].entry_id == "revenue" and answer.citations[0].model == "marts.fct_orders"
    assert len(answer.result_hash) == 64 and "SUM(items_revenue)" in answer.sql_plan.sql
    assert set(answer.timings_ms) >= {"retrieval", "llm", "sql", "total"}


def test_the_answer_can_be_sent_as_json(ask):
    answer, _ = ask([hit("revenue")], FakeLLM(REVENUE_2017))
    assert json.loads(answer.model_dump_json())["status"] == "answered"


def test_a_question_far_from_the_glossary_is_out_of_scope_without_calling_the_model(ask):
    answer, llm = ask([hit("revenue", similarity=0.2)])
    assert answer.status == "unsupported" and llm.calls == []
    assert "glossary" in answer.narrative and "glossaire" in answer.narrative


def test_no_hit_at_all_is_out_of_scope(ask):
    answer, llm = ask([])
    assert answer.status == "unsupported" and llm.calls == []


def test_churn_is_explained_not_computed(ask):
    answer, llm = ask([hit("churn", 0.65), hit("repurchase_rate", 0.56)])
    assert answer.status == "unsupported" and llm.calls == []
    assert answer.citations[0].entry_id == "churn" and answer.narrative


def test_a_concept_is_answered_from_the_glossary(ask):
    answer, llm = ask([hit("valid_order", 0.64)])
    assert answer.status == "definition" and llm.calls == []
    assert answer.citations[0].entry_id == "valid_order"
    assert answer.sql_plan is None


def test_an_invalid_intent_is_reported_and_nothing_is_executed(ask):
    answer, llm = ask([hit("revenue")], FakeLLM({"metrics": ["profit"], "confidence": 0.9}))
    assert answer.status == "error" and "invalid intent" in answer.errors[0]
    assert answer.sql_plan is None


def test_text_that_is_not_json_is_an_invalid_intent(ask):
    answer, _ = ask([hit("revenue")], FakeLLM("sorry, I cannot do that"))
    assert answer.status == "error" and "invalid intent" in answer.errors[0]


def test_a_rule_broken_by_the_model_is_caught(ask):
    answer, _ = ask([hit("revenue")], FakeLLM({"metrics": ["revenue"], "window_days": 90, "confidence": 0.9}))
    assert answer.status == "error" and "window_days" in answer.errors[0]


def test_a_low_confidence_intent_asks_for_clarification(ask):
    reply = {"metrics": ["revenue"], "confidence": 0.3, "clarification": "Which year?"}
    answer, _ = ask([hit("revenue")], FakeLLM(reply))
    assert answer.status == "needs_clarification" and answer.clarification == "Which year?"
    assert answer.sql_plan is None


def test_a_clarification_without_text_gets_a_default_question(ask):
    answer, _ = ask([hit("revenue")], FakeLLM({"metrics": ["revenue"], "confidence": 0.2}))
    assert answer.status == "needs_clarification" and answer.clarification


def test_an_unavailable_model_is_an_error_not_a_crash(ask):
    answer, _ = ask([hit("revenue")], FakeLLM(error=RuntimeError("Ollama answered 404: model not found")))
    assert answer.status == "error" and "language model unavailable" in answer.errors[0]


def test_a_refused_sql_plan_is_an_error(ask, monkeypatch):
    bad = SQLPlan(template_id="x", sql="DELETE FROM marts.fct_orders", params={}, row_limit=10)
    monkeypatch.setattr(pipeline, "build_plan", lambda intent: bad)
    answer, _ = ask([hit("revenue")], FakeLLM(REVENUE_2017))
    assert answer.status == "error" and "SQL refused" in answer.errors[0]


def test_retrieved_definitions_are_given_to_the_model_only_with_rag(ask):
    _, with_rag = ask([hit("revenue")], FakeLLM(REVENUE_2017), use_rag=True)
    _, without_rag = ask([hit("revenue")], FakeLLM(REVENUE_2017), use_rag=False)
    assert "closest to the question" in with_rag.calls[0][1]["content"]
    assert "closest to the question" not in without_rag.calls[0][1]["content"]


def test_a_metric_missing_from_the_hits_is_still_cited(ask):
    answer, _ = ask([hit("orders_count")], FakeLLM(REVENUE_2017))
    assert answer.status == "answered" and answer.citations[0].entry_id == "revenue"
    assert answer.citations[0].similarity == 0.0