import json
from datetime import date
from typing import get_args

import pytest
from pydantic import ValidationError

from askdata import glossary
from askdata.schemas import Answer, Citation, Dimension, Intent, MetricId, SQLPlan


def make_intent(**overrides):
    data = {"metrics": ["revenue"], "confidence": 0.9}
    data.update(overrides)
    return Intent(**data)


def make_plan(**overrides):
    data = {"template_id": "orders_metrics", "sql": "select 1", "params": {"a": 1}, "row_limit": 100}
    data.update(overrides)
    return SQLPlan(**data)


def make_citation():
    return Citation(entry_id="revenue", name="Revenue", model="marts.fct_orders", similarity=0.55)


# ---------- Intent ----------

def test_minimal_intent_is_valid():
    intent = make_intent()
    assert intent.metrics == ["revenue"]
    assert intent.dimensions == []


def test_full_intent_is_valid():
    intent = make_intent(
        metrics=["revenue"],
        dimensions=["product_category"],
        filters=[{"dimension": "customer_state", "op": "in", "values": ["SP", "RJ"]}],
        time_grain="month",
        date_from=date(2017, 1, 1),
        date_to=date(2017, 12, 31),
    )
    assert intent.time_grain == "month"
    assert intent.filters[0].values == ["SP", "RJ"]


@pytest.mark.parametrize("metric", ["profit", "churn", "REVENUE"])
def test_unknown_metric_is_rejected(metric):
    with pytest.raises(ValidationError):
        make_intent(metrics=[metric])


@pytest.mark.parametrize("extra", [{"sql": "select 1"}, {"table": "raw.orders"}])
def test_extra_fields_are_rejected(extra):
    with pytest.raises(ValidationError):
        make_intent(**extra)


def test_dimension_must_be_allowed_for_the_metric():
    with pytest.raises(ValidationError):
        make_intent(metrics=["average_basket"], dimensions=["product_category"])


def test_filter_dimension_must_be_allowed_for_the_metric():
    with pytest.raises(ValidationError):
        make_intent(metrics=["orders_count"], filters=[{"dimension": "product_category", "values": ["toys"]}])


def test_metrics_from_different_tables_are_rejected():
    with pytest.raises(ValidationError):
        make_intent(metrics=["revenue", "repurchase_rate"])


def test_duplicate_metrics_are_rejected():
    with pytest.raises(ValidationError):
        make_intent(metrics=["revenue", "revenue"])


def test_window_days_only_for_repurchase_rate():
    with pytest.raises(ValidationError):
        make_intent(metrics=["revenue"], window_days=90)


def test_window_days_accepted_for_repurchase_rate():
    assert make_intent(metrics=["repurchase_rate"], window_days=90).window_days == 90


def test_date_range_must_be_ordered():
    with pytest.raises(ValidationError):
        make_intent(date_from=date(2018, 1, 1), date_to=date(2017, 1, 1))


def test_top_k_needs_a_dimension():
    with pytest.raises(ValidationError):
        make_intent(top_k=5)

def test_top_k_cannot_be_combined_with_time_grain():
    with pytest.raises(ValidationError):
        make_intent(dimensions=["customer_state"], time_grain="month", top_k=5)
    assert make_intent(dimensions=["customer_state"], top_k=5).top_k == 5
    
@pytest.mark.parametrize("top_k", [0, 51])
def test_top_k_bounds(top_k):
    with pytest.raises(ValidationError):
        make_intent(dimensions=["customer_state"], top_k=top_k)


@pytest.mark.parametrize("confidence", [-0.1, 1.5])
def test_confidence_bounds(confidence):
    with pytest.raises(ValidationError):
        make_intent(confidence=confidence)


@pytest.mark.parametrize("value", ["SP'; DROP TABLE x;--", "a b; c", "x" * 61])
def test_unsafe_filter_values_are_rejected(value):
    with pytest.raises(ValidationError):
        make_intent(filters=[{"dimension": "customer_state", "values": [value]}])


def test_safe_filter_values_are_accepted():
    intent = make_intent(
        filters=[
            {"dimension": "customer_state", "values": ["SP", "RJ"]},
            {"dimension": "product_category", "op": "not_in", "values": ["bed_bath_table"]},
        ]
    )
    assert len(intent.filters) == 2


@pytest.mark.parametrize("confidence, clarification, expected", [
    (0.9, None, False),
    (0.3, None, True),
    (0.9, "Which year do you mean?", True),
])
def test_needs_clarification(confidence, clarification, expected):
    assert make_intent(confidence=confidence, clarification=clarification).needs_clarification is expected


def test_literals_match_the_glossary():
    """If the glossary gains or loses a metric or a dimension, the schemas must be updated."""
    assert set(get_args(MetricId)) == set(glossary.metrics())
    allowed = set().union(*(glossary.allowed_dimensions(m) for m in glossary.metrics()))
    assert set(get_args(Dimension)) == allowed


def test_json_schema_lists_the_metrics():
    """The JSON schema is what a local LLM can be constrained with."""
    schema = json.dumps(Intent.model_json_schema())
    for metric in get_args(MetricId):
        assert f'"{metric}"' in schema


# ---------- SQLPlan ----------

def test_sql_plan_hash_is_stable_and_sensitive():
    a, b, c = make_plan(), make_plan(), make_plan(params={"a": 2})
    assert a.plan_hash == b.plan_hash
    assert a.plan_hash != c.plan_hash
    assert len(a.plan_hash) == 64


def test_sql_plan_survives_a_round_trip():
    plan = make_plan()
    assert SQLPlan.model_validate(plan.model_dump()).plan_hash == plan.plan_hash


@pytest.mark.parametrize("row_limit", [0, 1001])
def test_sql_plan_row_limit_bounds(row_limit):
    with pytest.raises(ValidationError):
        make_plan(row_limit=row_limit)


# ---------- Answer ----------

def test_answered_requires_a_citation_and_a_plan():
    with pytest.raises(ValidationError):
        Answer(question="q", status="answered", sql_plan=make_plan(), narrative="n", citations=[])
    with pytest.raises(ValidationError):
        Answer(question="q", status="answered", narrative="n", citations=[make_citation()])


def test_answered_is_valid_with_plan_narrative_and_citation():
    answer = Answer(question="q", status="answered", sql_plan=make_plan(), narrative="n",
                    citations=[make_citation()], columns=["month", "revenue"], rows=[["2017-01", 1.0]])
    assert answer.status == "answered"


def test_clarification_status_requires_a_question():
    with pytest.raises(ValidationError):
        Answer(question="q", status="needs_clarification")
    assert Answer(question="q", status="needs_clarification", clarification="Which year?").clarification


def test_error_status_requires_errors():
    with pytest.raises(ValidationError):
        Answer(question="q", status="error")
    assert Answer(question="q", status="error", errors=["timeout"]).errors == ["timeout"]


def test_definition_requires_narrative_and_citation():
    with pytest.raises(ValidationError):
        Answer(question="q", status="definition", narrative="n")
    assert Answer(question="q", status="definition", narrative="n", citations=[make_citation()])


def test_unsupported_requires_a_narrative():
    with pytest.raises(ValidationError):
        Answer(question="q", status="unsupported")
    assert Answer(question="q", status="unsupported", narrative="Out of scope.")


def test_preview_is_limited_to_100_rows():
    with pytest.raises(ValidationError):
        Answer(question="q", status="error", errors=["x"], rows=[[1]] * 101)