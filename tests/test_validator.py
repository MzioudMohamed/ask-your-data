from datetime import date

import pytest

from askdata import glossary
from askdata.schemas import Intent, SQLPlan
from askdata.sql.templates import build_plan
from askdata.sql.validator import SQLValidationError, check_sql, expected_columns, validate_plan

OK = "SELECT SUM(items_revenue) AS revenue FROM marts.fct_orders WHERE is_valid_order LIMIT 10"


def make_intent(**overrides):
    data = {"metrics": ["revenue"], "confidence": 0.9}
    data.update(overrides)
    return Intent(**data)


def test_a_simple_select_is_accepted():
    assert check_sql(OK, row_limit=10, declared_tables=["marts.fct_orders"]) == []


@pytest.mark.parametrize("metric", sorted(glossary.metrics()))
def test_every_template_plan_is_accepted(metric):
    for kwargs in (
        {},
        {"time_grain": "year", "date_from": date(2017, 1, 1), "date_to": date(2017, 12, 31)},
        {"dimensions": ["customer_state"], "top_k": 3,
         "filters": [{"dimension": "customer_state", "op": "not_in", "values": ["SP"]}]},
    ):
        plan = build_plan(make_intent(metrics=[metric], **kwargs))
        assert validate_plan(plan) is plan


def test_item_level_and_multi_metric_plans_are_accepted():
    for kwargs in (
        {"metrics": ["revenue"], "dimensions": ["product_category", "seller_state"]},
        {"metrics": ["orders_count", "delivery_time"], "dimensions": ["customer_state"]},
    ):
        plan = build_plan(make_intent(**kwargs))
        assert check_sql(plan.sql, plan.params, plan.row_limit, plan.tables) == []


@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM marts.fct_orders LIMIT 1; SELECT 2 FROM marts.fct_orders LIMIT 1",
    "DROP TABLE marts.fct_orders",
    "DELETE FROM marts.fct_orders",
    "UPDATE marts.fct_orders SET order_status = 'x'",
    "INSERT INTO marts.fct_orders (order_id) VALUES ('x')",
    "TRUNCATE marts.fct_orders",
    "CREATE TABLE marts.hack AS SELECT 1 AS a",
    "COPY marts.fct_orders TO '/tmp/out.csv'",
    "SELECT order_id INTO marts.hack FROM marts.fct_orders LIMIT 1",
    "GRANT ALL ON marts.fct_orders TO public",
    "SET default_transaction_read_only = off",
])
def test_anything_but_a_single_select_is_refused(sql):
    assert check_sql(sql) != []


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) AS n FROM raw.orders LIMIT 1",
    "SELECT COUNT(*) AS n FROM staging.stg_orders LIMIT 1",
    "SELECT COUNT(*) AS n FROM rag.glossary_chunks LIMIT 1",
    "SELECT COUNT(*) AS n FROM public.anything LIMIT 1",
    "SELECT COUNT(*) AS n FROM fct_orders LIMIT 1",
    "SELECT COUNT(*) AS n FROM askdata.marts.fct_orders LIMIT 1",
    "SELECT COUNT(*) AS n FROM information_schema.tables LIMIT 1",
    "SELECT COUNT(*) AS n FROM pg_catalog.pg_user LIMIT 1",
    "SELECT COUNT(*) AS n FROM marts.not_a_mart LIMIT 1",
])
def test_tables_outside_the_whitelist_are_refused(sql):
    assert any("table not allowed" in hit for hit in check_sql(sql))


@pytest.mark.parametrize("sql", [
    "SELECT pg_sleep(5) AS s FROM marts.fct_orders LIMIT 1",
    "SELECT pg_read_file('/etc/passwd') AS f FROM marts.fct_orders LIMIT 1",
    "SELECT set_config('x', 'y', false) AS c FROM marts.fct_orders LIMIT 1",
    "SELECT lo_import('/etc/passwd') AS l FROM marts.fct_orders LIMIT 1",
    "SELECT current_setting('server_version') AS v FROM marts.fct_orders LIMIT 1",
])
def test_unknown_functions_are_refused(sql):
    assert check_sql(sql) != []


@pytest.mark.parametrize("sql", [
    "SELECT order_id FROM marts.fct_orders UNION ALL SELECT order_id FROM marts.fct_orders LIMIT 5",
    "SELECT a.order_id FROM marts.fct_orders a JOIN marts.fct_order_items b ON a.order_id = b.order_id LIMIT 5",
    "SELECT order_id FROM (SELECT order_id FROM marts.fct_orders) t LIMIT 5",
    "WITH t AS (SELECT order_id FROM marts.fct_orders) SELECT order_id FROM t LIMIT 5",
    "SELECT order_id FROM marts.fct_orders WHERE order_id IN (SELECT order_id FROM marts.fct_order_items) LIMIT 5",
    "SELECT DISTINCT order_id FROM marts.fct_orders LIMIT 5",
    "SELECT order_id FROM marts.fct_orders LIMIT 5 FOR UPDATE",
    "SELECT SUM(items_revenue) OVER () AS s FROM marts.fct_orders LIMIT 5",
    "SELECT * FROM marts.fct_orders LIMIT 5",
])
def test_constructs_outside_the_whitelist_are_refused(sql):
    assert check_sql(sql) != []


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) AS n FROM marts.fct_orders WHERE customer_state = 'SP' LIMIT 5",
    "SELECT COUNT(*) AS n FROM marts.fct_orders WHERE order_status = 'a' OR 1 = 1 LIMIT 5",
])
def test_string_literals_are_refused_values_must_be_parameters(sql):
    assert any("string literal" in hit for hit in check_sql(sql))


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) AS n FROM marts.fct_orders LIMIT 5 -- hidden",
    "SELECT COUNT(*) AS n /* hidden */ FROM marts.fct_orders LIMIT 5",
    "SELECT COUNT(*) AS n FROM marts.fct_orders LIMIT 5;",
])
def test_comments_and_semicolons_are_refused(sql):
    assert check_sql(sql) != []


@pytest.mark.parametrize("sql, expected_hit", [
    ("SELECT COUNT(*) AS n FROM marts.fct_orders", "LIMIT is required"),
    ("SELECT COUNT(*) AS n FROM marts.fct_orders LIMIT 100000", "LIMIT above"),
    ("SELECT COUNT(*) AS n FROM marts.fct_orders LIMIT ALL", "LIMIT"),
])
def test_limit_is_required_and_bounded(sql, expected_hit):
    assert any(expected_hit in hit for hit in check_sql(sql))


def test_limit_must_match_the_plan_row_limit():
    assert any("differs from the plan" in hit for hit in check_sql(OK, row_limit=5))


def test_placeholders_must_match_the_parameters():
    sql = "SELECT COUNT(*) AS n FROM marts.fct_orders WHERE customer_state = ANY(%(a)s) LIMIT 5"
    assert check_sql(sql, {"a": ["SP"]}) == []
    assert any("do not match" in hit for hit in check_sql(sql, {}))
    assert any("do not match" in hit for hit in check_sql(sql, {"a": ["SP"], "unused": 1}))
    assert any("stray" in hit for hit in check_sql(sql.replace("%(a)s", "%s"), {}))


def test_declared_tables_must_match_the_tables_read():
    hits = check_sql(OK, row_limit=10, declared_tables=["marts.dim_customers"])
    assert any("declared tables" in hit for hit in hits)


def test_unparsable_sql_is_refused():
    assert any("cannot parse" in hit or "exactly one" in hit for hit in check_sql("SELEC FROM WHERE"))


def test_validate_plan_raises_with_the_hits():
    plan = SQLPlan(template_id="x", sql="DELETE FROM marts.fct_orders", params={}, row_limit=10)
    with pytest.raises(SQLValidationError) as error:
        validate_plan(plan)
    assert error.value.hits


def test_expected_columns_come_from_the_select_list():
    sql = "SELECT purchase_month AS period, customer_state, SUM(items_revenue) AS revenue FROM marts.fct_orders LIMIT 5"
    assert expected_columns(sql) == ["period", "customer_state", "revenue"]