from datetime import date

import psycopg
import pytest
import sqlglot
from sqlglot import exp

from askdata import config, glossary
from askdata.schemas import Intent
from askdata.sql.templates import DEFAULT_ROW_LIMIT, TABLES, build_plan, with_filters


def make_intent(**overrides):
    data = {"metrics": ["revenue"], "confidence": 0.9}
    data.update(overrides)
    return Intent(**data)


def run(sql, params=None):
    """Run SQL with the read-only role, the way the copilot will."""
    with psycopg.connect(**config.DB_READER, autocommit=True) as conn:
        return conn.execute(sql, params or {}).fetchall()


# ---------- plan structure (no database needed) ----------

@pytest.mark.parametrize("metric", sorted(glossary.metrics()))
def test_every_metric_builds_a_plan(metric):
    plan = build_plan(make_intent(metrics=[metric]))
    assert plan.tables[0] in TABLES
    assert f"AS {metric}" in plan.sql


@pytest.mark.parametrize("kwargs, template_id, table", [
    ({"metrics": ["revenue"], "dimensions": ["customer_state"]}, "orders_metrics", "marts.fct_orders"),
    ({"metrics": ["revenue"], "dimensions": ["product_category"]}, "order_items_metrics", "marts.fct_order_items"),
    ({"metrics": ["revenue"], "dimensions": ["seller_state"]}, "order_items_metrics", "marts.fct_order_items"),
    ({"metrics": ["revenue"], "filters": [{"dimension": "product_category", "values": ["toys"]}]},
     "order_items_metrics", "marts.fct_order_items"),
    ({"metrics": ["orders_count"], "dimensions": ["order_status"]}, "orders_metrics", "marts.fct_orders"),
    ({"metrics": ["repurchase_rate"]}, "repurchase_metrics", "marts.dim_customers"),
])
def test_template_choice(kwargs, template_id, table):
    plan = build_plan(make_intent(**kwargs))
    assert plan.template_id == template_id
    assert plan.tables == [table]
    assert f"FROM {table}" in plan.sql


def test_filter_values_travel_as_parameters_not_in_the_sql():
    plan = build_plan(make_intent(filters=[{"dimension": "customer_state", "values": ["SP", "RJ"]}]))
    assert plan.params == {"filter_0": ["SP", "RJ"]}
    assert "SP" not in plan.sql and "RJ" not in plan.sql
    assert "ANY(%(filter_0)s)" in plan.sql


def test_not_in_filter_negates_any():
    plan = build_plan(make_intent(filters=[{"dimension": "customer_state", "op": "not_in", "values": ["SP"]}]))
    assert "NOT (customer_state = ANY(%(filter_0)s))" in plan.sql


def test_date_range_is_inclusive_of_the_last_day():
    plan = build_plan(make_intent(date_from=date(2017, 1, 1), date_to=date(2017, 12, 31)))
    assert plan.params["date_from"] == date(2017, 1, 1)
    assert plan.params["date_to_exclusive"] == date(2018, 1, 1)
    assert "purchased_at >= %(date_from)s" in plan.sql and "purchased_at < %(date_to_exclusive)s" in plan.sql


def test_repurchase_dates_apply_to_the_first_purchase():
    plan = build_plan(make_intent(metrics=["repurchase_rate"], date_from=date(2017, 1, 1)))
    assert "first_purchase_at >= %(date_from)s" in plan.sql


def test_year_grain_truncates_to_the_year():
    plan = build_plan(make_intent(time_grain="year"))
    assert "date_trunc('year', purchase_month)::date AS period" in plan.sql


def test_repurchase_window_defaults_to_180_days_and_can_be_90():
    default = build_plan(make_intent(metrics=["repurchase_rate"]))
    short = build_plan(make_intent(metrics=["repurchase_rate"], window_days=90))
    assert "repurchased_within_180d" in default.sql and "90d" not in default.sql
    assert "repurchased_within_90d" in short.sql and "180d" not in short.sql


def test_top_k_sets_the_limit_and_ranks_by_the_first_metric():
    plan = build_plan(make_intent(dimensions=["customer_state"], top_k=5))
    assert plan.row_limit == 5 and plan.sql.rstrip().endswith("LIMIT 5")
    assert "ORDER BY revenue DESC NULLS LAST" in plan.sql
    asc = build_plan(make_intent(dimensions=["customer_state"], top_k=5, sort="asc"))
    assert "ORDER BY revenue ASC NULLS LAST" in asc.sql


def test_default_limit_and_no_group_by_without_breakdown():
    plan = build_plan(make_intent())
    assert plan.row_limit == DEFAULT_ROW_LIMIT and f"LIMIT {DEFAULT_ROW_LIMIT}" in plan.sql
    assert "GROUP BY" not in plan.sql and "ORDER BY" not in plan.sql


def test_identical_row_filters_are_listed_once():
    plan = build_plan(make_intent(metrics=["revenue", "orders_count"]))
    assert "WHERE is_valid_order\n" in plan.sql


def test_every_plan_parses_and_reads_only_whitelisted_tables():
    plan = build_plan(make_intent(metrics=["revenue", "orders_count", "delivery_time"], dimensions=["customer_state"]))
    tree = sqlglot.parse_one(plan.sql, read="postgres")
    tables = {f"{t.db}.{t.name}" for t in tree.find_all(exp.Table)}
    assert tables == set(plan.tables) and tables <= set(TABLES)


def test_with_filters_adds_the_filter_to_every_aggregate():
    sql = with_filters("sum(x) / nullif(count(*), 0)", ["f"])
    assert sql.count("FILTER") == 2
    combined = with_filters("count(*) filter (where g) * 1.0 / nullif(count(*), 0)", ["f"])
    assert combined.count("FILTER") == 2 and "g AND f" in combined


def test_plan_hash_depends_on_the_intent():
    a = build_plan(make_intent(filters=[{"dimension": "customer_state", "values": ["SP"]}]))
    b = build_plan(make_intent(filters=[{"dimension": "customer_state", "values": ["RJ"]}]))
    assert a.plan_hash != b.plan_hash


# ---------- gold pairs: the generated SQL must return the same rows as a hand-written query ----------
# Each golden query states the metric definition directly with a WHERE clause, independently of the glossary.

GOLD = [
    (
        "revenue by month in 2017",
        {"metrics": ["revenue"], "time_grain": "month", "date_from": date(2017, 1, 1), "date_to": date(2017, 12, 31)},
        """select purchase_month, sum(items_revenue) from marts.fct_orders
           where is_valid_order and purchased_at >= '2017-01-01' and purchased_at < '2018-01-01'
           group by 1""",
    ),
    (
        "revenue by state",
        {"metrics": ["revenue"], "dimensions": ["customer_state"]},
        """select customer_state, sum(items_revenue) from marts.fct_orders where is_valid_order group by 1""",
    ),
    (
        "top 3 categories by revenue, SP and RJ only",
        {"metrics": ["revenue"], "dimensions": ["product_category"], "top_k": 3,
         "filters": [{"dimension": "customer_state", "values": ["SP", "RJ"]}]},
        """select product_category, sum(price) from marts.fct_order_items
           where is_valid_order and customer_state in ('SP', 'RJ') group by 1 order by 2 desc, 1 limit 3""",
    ),
    (
        "orders by status outside SP",
        {"metrics": ["orders_count"], "dimensions": ["order_status"],
         "filters": [{"dimension": "customer_state", "op": "not_in", "values": ["SP"]}]},
        """select order_status, count(*) from marts.fct_orders
           where is_valid_order and customer_state <> 'SP' group by 1""",
    ),
    (
        "average basket overall",
        {"metrics": ["average_basket"]},
        """select sum(items_revenue) / count(*) from marts.fct_orders where is_valid_order and items_count > 0""",
    ),
    (
        "delivery time by state",
        {"metrics": ["delivery_time"], "dimensions": ["customer_state"]},
        """select customer_state, avg(delivery_days) from marts.fct_orders where has_delivery_data group by 1""",
    ),
    (
        "late delivery rate by month",
        {"metrics": ["late_delivery_rate"], "time_grain": "month"},
        """select purchase_month, sum(case when is_late then 1 else 0 end) * 1.0 / count(*)
           from marts.fct_orders where has_delivery_data group by 1""",
    ),
    (
        "average review score by year",
        {"metrics": ["average_review_score"], "time_grain": "year"},
        """select date_trunc('year', purchase_month)::date, avg(review_score) from marts.fct_orders
           where is_valid_order and review_score is not null group by 1""",
    ),
    (
        "repurchase rate at 180 days by cohort month",
        {"metrics": ["repurchase_rate"], "time_grain": "month"},
        """select cohort_month, sum(case when repurchased_within_180d then 1 else 0 end) * 1.0 / count(*)
           from marts.dim_customers where is_observable_180d group by 1""",
    ),
    (
        "repurchase rate at 90 days by state",
        {"metrics": ["repurchase_rate"], "dimensions": ["customer_state"], "window_days": 90},
        """select customer_state, sum(case when repurchased_within_90d then 1 else 0 end) * 1.0 / count(*)
           from marts.dim_customers where is_observable_90d group by 1""",
    ),
    (
        "revenue and orders by state (two metrics in one query)",
        {"metrics": ["revenue", "orders_count"], "dimensions": ["customer_state"]},
        """select customer_state, sum(items_revenue), count(*) from marts.fct_orders where is_valid_order group by 1""",
    ),
    (
        "delivery time and orders together (different row filters in one query)",
        {"metrics": ["orders_count", "delivery_time"], "dimensions": ["customer_state"]},
        """select customer_state,
                  count(*) filter (where is_valid_order),
                  avg(delivery_days) filter (where has_delivery_data)
           from marts.fct_orders group by 1""",
    ),
]


@pytest.mark.parametrize("label, kwargs, golden", GOLD, ids=[g[0] for g in GOLD])
def test_generated_sql_matches_the_golden_query(label, kwargs, golden):
    plan = build_plan(make_intent(**kwargs))
    generated = run(plan.sql, plan.params)
    expected = run(golden)
    assert sorted(map(repr, generated)) == sorted(map(repr, expected))
    assert len(generated) > 0


def test_top_k_returns_at_most_k_rows_in_order():
    plan = build_plan(make_intent(dimensions=["customer_state"], top_k=2))
    rows = run(plan.sql, plan.params)
    assert len(rows) <= 2
    assert [r[1] for r in rows] == sorted((r[1] for r in rows), reverse=True)


def test_an_unusual_but_legal_filter_value_stays_out_of_the_sql():
    """Values travel as parameters: even a legal but unusual value never appears in the SQL text."""
    plan = build_plan(make_intent(filters=[{"dimension": "customer_state", "values": ["x-y z"]}]))
    assert "x-y z" not in plan.sql
    assert run(plan.sql, plan.params) is not None