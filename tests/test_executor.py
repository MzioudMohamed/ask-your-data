from datetime import date

import pytest

from askdata.schemas import Intent, SQLPlan
from askdata.sql.executor import ExecutionError, execute, run_intent
from askdata.sql.validator import SQLValidationError


def make_intent(**overrides):
    data = {"metrics": ["revenue"], "confidence": 0.9}
    data.update(overrides)
    return Intent(**data)


def make_plan(sql, params=None, row_limit=10, tables=None):
    return SQLPlan(template_id="test", sql=sql, params=params or {}, row_limit=row_limit,
                   tables=tables or ["marts.fct_orders"])


def test_run_intent_returns_rows_columns_and_a_hash():
    plan, result = run_intent(make_intent(time_grain="month", date_from=date(2017, 1, 1), date_to=date(2017, 12, 31)))
    assert result.columns == ["period", "revenue"]
    assert 0 < result.row_count <= plan.row_limit
    assert len(result.result_hash) == 64 and result.elapsed_ms > 0


def test_same_plan_gives_the_same_result_hash():
    intent = make_intent(dimensions=["customer_state"], top_k=3)
    _, first = run_intent(intent)
    _, second = run_intent(intent)
    assert first.result_hash == second.result_hash


def test_different_plans_give_different_hashes():
    _, a = run_intent(make_intent(dimensions=["customer_state"]))
    _, b = run_intent(make_intent(metrics=["orders_count"], dimensions=["customer_state"]))
    assert a.result_hash != b.result_hash


def test_preview_is_json_friendly_and_limited():
    _, result = run_intent(make_intent(time_grain="month"))
    preview = result.preview(limit=3)
    assert len(preview) <= 3
    for row in preview:
        assert all(isinstance(v, (str, float, int, type(None))) for v in row)


def test_top_k_is_respected_and_sorted():
    _, result = run_intent(make_intent(dimensions=["customer_state"], top_k=2))
    assert result.row_count <= 2
    values = [row[1] for row in result.rows]
    assert values == sorted(values, reverse=True)


def test_an_empty_result_is_not_an_error():
    _, result = run_intent(make_intent(filters=[{"dimension": "customer_state", "values": ["ZZ"]}], time_grain="month"))
    assert result.row_count == 0


def test_a_refused_plan_never_reaches_the_database():
    with pytest.raises(SQLValidationError):
        execute(make_plan("DELETE FROM marts.fct_orders"))
    with pytest.raises(SQLValidationError):
        execute(make_plan("SELECT COUNT(*) AS n FROM raw.orders LIMIT 10", tables=["raw.orders"]))


def test_database_errors_are_reported_with_a_kind():
    plan = make_plan("SELECT nonexistent_column AS x FROM marts.fct_orders LIMIT 10")
    with pytest.raises(ExecutionError) as error:
        execute(plan)
    assert error.value.kind == "database" and "nonexistent_column" in str(error.value)


def test_division_by_zero_is_a_database_error_not_a_crash():
    plan = make_plan("SELECT 1 / 0 AS x FROM marts.fct_orders LIMIT 10")
    with pytest.raises(ExecutionError) as error:
        execute(plan)
    assert error.value.kind == "database"