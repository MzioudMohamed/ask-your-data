"""Turn a validated Intent into a SQLPlan.

The SQL is assembled from two trusted sources only:
- the metric definitions in glossary/metrics.yml (expression and row filters),
- the fixed whitelist of tables and columns below.
Values coming from the user (dates, filter values) are never pasted into the SQL: they travel as parameters.
"""
import re
from datetime import timedelta

import sqlglot
from sqlglot import exp

from askdata import glossary
from askdata.schemas import Intent, SQLPlan

DEFAULT_ROW_LIMIT = 1000

# The only tables the copilot may read, with the columns used for time breakdowns and date ranges.
TABLES = {
    "marts.fct_orders": {
        "template_id": "orders_metrics", "time_column": "purchase_month", "date_column": "purchased_at",
    },
    "marts.fct_order_items": {
        "template_id": "order_items_metrics", "time_column": "purchase_month", "date_column": "purchased_at",
    },
    "marts.dim_customers": {
        "template_id": "repurchase_metrics", "time_column": "cohort_month", "date_column": "first_purchase_at",
    },
}

IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class TemplateError(ValueError):
    """The intent cannot be turned into SQL."""


def _parse(sql):
    return sqlglot.parse_one(sql, read="postgres")


def _condition(filters):
    """AND of the row filters of a metric, as a sqlglot expression."""
    return exp.and_(*[_parse(f) for f in filters])


def with_filters(sql_expression, filters):
    """Apply the row filters of a metric inside every aggregate of its expression.

    sum(x)                        ->  sum(x) FILTER (WHERE f)
    count(*) FILTER (WHERE g)     ->  count(*) FILTER (WHERE g AND f)

    Each metric then carries its own filters, so several metrics can share one query.
    """
    condition = _condition(filters)

    def add_filter(node):
        if isinstance(node, exp.Filter):
            node.set("expression", exp.Where(this=exp.and_(node.expression.this, condition.copy())))
            return node
        if isinstance(node, exp.AggFunc) and not isinstance(node.parent, exp.Filter):
            return exp.Filter(this=node, expression=exp.Where(this=condition.copy()))
        return node

    return _parse(sql_expression).transform(add_filter).sql(dialect="postgres")


def _needs_item_grain(intent):
    """True when a dimension or filter exists only at item level (for example product_category)."""
    used = set(intent.dimensions) | {f.dimension for f in intent.filters}
    return any(
        dimension not in glossary.metrics()[metric].get("dimensions", [])
        for metric in intent.metrics
        for dimension in used
    )


def _metric_parts(metric_id, item_grain, window_days):
    """(table, sql expression, row filters) of a metric, read from the glossary."""
    entry = glossary.metrics()[metric_id]
    if entry["model"] == "marts.dim_customers":
        suffix = f"_{window_days or 180}d"
        return entry["model"], entry["sql" + suffix], entry["filters" + suffix]
    if item_grain:
        if "alt_sql" not in entry:
            raise TemplateError(f"{metric_id} cannot be computed at item level")
        return entry["alt_model"], entry["alt_sql"], entry["filters"]
    return entry["model"], entry["sql"], entry["filters"]


def build_plan(intent: Intent) -> SQLPlan:
    item_grain = _needs_item_grain(intent)
    parts = [_metric_parts(m, item_grain, intent.window_days) for m in intent.metrics]

    tables = {table for table, _, _ in parts}
    if len(tables) != 1:
        raise TemplateError(f"metrics read different tables: {sorted(tables)}")
    table = tables.pop()
    if table not in TABLES:
        raise TemplateError(f"table not allowed: {table}")
    settings = TABLES[table]

    for name in [*intent.metrics, *intent.dimensions]:
        if not IDENTIFIER.match(name):
            raise TemplateError(f"unsafe identifier: {name}")

    select, group_by = [], []
    if intent.time_grain:
        column = settings["time_column"]
        expression = column if intent.time_grain == "month" else f"date_trunc('year', {column})::date"
        select.append(f"{expression} AS period")
        group_by.append(expression)
    for dimension in intent.dimensions:
        select.append(dimension)
        group_by.append(dimension)

    row_filters = []
    for metric, (_, sql, filters) in zip(intent.metrics, parts):
        select.append(f"{with_filters(sql, filters)} AS {metric}")
        row_filters.append(_condition(filters))
    # Keep only rows that count for at least one of the metrics (identical filters are listed once).
    unique_filters = list({f.sql(dialect="postgres"): f for f in row_filters}.values())
    keep = unique_filters[0].sql(dialect="postgres") if len(unique_filters) == 1 else (
        "(" + exp.or_(*unique_filters).sql(dialect="postgres") + ")"
    )

    where, params = [keep], {}
    if intent.date_from:
        where.append(f"{settings['date_column']} >= %(date_from)s")
        params["date_from"] = intent.date_from
    if intent.date_to:
        where.append(f"{settings['date_column']} < %(date_to_exclusive)s")
        params["date_to_exclusive"] = intent.date_to + timedelta(days=1)
    for i, f in enumerate(intent.filters):
        name = f"filter_{i}"
        where.append(f"{f.dimension} = ANY(%({name})s)" if f.op == "in" else f"{f.dimension} <> ALL(%({name})s)")
        params[name] = list(f.values)

    if intent.time_grain:
        order_by = ", ".join(["period", *intent.dimensions])
    elif intent.dimensions:
        order_by = ", ".join([f"{intent.metrics[0]} {intent.sort.upper()} NULLS LAST", *intent.dimensions])
    else:
        order_by = ""
    limit = intent.top_k or DEFAULT_ROW_LIMIT

    lines = ["SELECT", "    " + ",\n    ".join(select), f"FROM {table}", "WHERE " + "\n  AND ".join(where)]
    if group_by:
        lines.append("GROUP BY " + ", ".join(group_by))
    if order_by:
        lines.append("ORDER BY " + order_by)
    lines.append(f"LIMIT {limit}")

    return SQLPlan(
        template_id=settings["template_id"],
        sql="\n".join(lines),
        params=params,
        row_limit=limit,
        tables=[table],
    )