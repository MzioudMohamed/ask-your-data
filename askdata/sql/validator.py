"""Independent safety check of the final SQL, whatever produced it.

Default deny: the SQL is parsed with sqlglot and only a short list of constructs is accepted.
Anything else (writes, joins, subqueries, unknown functions, string literals, other tables...) is reported
as a "hit" and the query is refused. This is the second wall, after the schemas and before the read-only role.
"""
import re

import sqlglot
from sqlglot import exp

from askdata.schemas import SQLPlan
from askdata.sql.templates import TABLES

MAX_ROWS = 1000

# The only syntax tree nodes accepted. SELECT ... FROM one table WHERE ... GROUP BY ... ORDER BY ... LIMIT n,
# with a few aggregates and operators. No JOIN, subquery, CTE, UNION, window, DISTINCT or INTO.
ALLOWED_NODES = {
    exp.Select, exp.From, exp.Table, exp.Where, exp.Group, exp.Order, exp.Ordered, exp.Limit,
    exp.Alias, exp.Column, exp.Identifier, exp.Literal, exp.Null, exp.Paren, exp.Placeholder,
    exp.Star, exp.Var, exp.DataType, exp.Cast, exp.TimestampTrunc, exp.Filter,
    exp.Sum, exp.Count, exp.Avg, exp.Min, exp.Max, exp.Nullif,
    exp.And, exp.Or, exp.Not, exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Is, exp.Any,
    exp.Add, exp.Sub, exp.Mul, exp.Div,
}

PLACEHOLDER = re.compile(r"%\((\w+)\)s")
RAW_DENYLIST = {
    ";": "semicolon (stacked statements)",
    "--": "SQL comment",
    "/*": "SQL comment",
}


class SQLValidationError(ValueError):
    def __init__(self, hits):
        self.hits = list(hits)
        super().__init__("SQL refused: " + "; ".join(self.hits))


def check_sql(sql, params=None, row_limit=None, declared_tables=None):
    """Return the list of problems found in the SQL (empty list means the SQL is accepted)."""
    params = params or {}
    hits = []

    for pattern, label in RAW_DENYLIST.items():
        if pattern in sql:
            hits.append(f"forbidden pattern: {label}")

    # Placeholders must be exactly the declared parameters, and no other '%' may appear.
    names = set(PLACEHOLDER.findall(sql))
    if "%" in PLACEHOLDER.sub("", sql):
        hits.append("stray '%' (only %(name)s placeholders are allowed)")
    if names != set(params):
        hits.append(f"placeholders {sorted(names)} do not match parameters {sorted(params)}")

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.SqlglotError as error:
        return hits + [f"cannot parse the SQL: {str(error).splitlines()[0]}"]
    if len(statements) != 1 or statements[0] is None:
        return hits + ["exactly one statement is required"]
    tree = statements[0]
    if type(tree) is not exp.Select:
        return hits + [f"only SELECT is allowed, found {type(tree).__name__}"]

    for node in tree.find_all(exp.Expression):
        kind = type(node)
        if kind not in ALLOWED_NODES:
            hits.append(f"construct not allowed: {kind.__name__}")
        elif kind is exp.Literal and node.is_string:
            hits.append("string literal not allowed (values must be parameters)")
        elif kind is exp.Star and type(node.parent) is not exp.Count:
            hits.append("SELECT * is not allowed")
        elif kind is exp.Var and not (type(node.parent) is exp.TimestampTrunc and node.name.upper() in {"YEAR", "MONTH"}):
            hits.append(f"identifier-like token not allowed: {node.name}")
        elif kind is exp.DataType and node.this != exp.DataType.Type.DATE:
            hits.append("only the DATE type is allowed in a cast")

    # Full name with every part, so a catalog prefix (database.marts.table) is not silently ignored.
    tables = {".".join(part for part in (t.catalog, t.db, t.name) if part) for t in tree.find_all(exp.Table)}
    for table in sorted(tables):
        if table not in TABLES:
            hits.append(f"table not allowed: {table}")
    if declared_tables is not None and tables != set(declared_tables):
        hits.append(f"declared tables {sorted(declared_tables)} differ from the tables read {sorted(tables)}")

    limit = tree.args.get("limit")
    if limit is None:
        hits.append("LIMIT is required")
    else:
        value = limit.expression
        if not (isinstance(value, exp.Literal) and not value.is_string and value.name.isdigit()):
            hits.append("LIMIT must be a plain number")
        elif int(value.name) > MAX_ROWS:
            hits.append(f"LIMIT above {MAX_ROWS}")
        elif row_limit is not None and int(value.name) != row_limit:
            hits.append(f"LIMIT {value.name} differs from the plan row_limit {row_limit}")

    # Remove duplicates, keep the order.
    return list(dict.fromkeys(hits))


def expected_columns(sql):
    """Names of the columns the query must return, read from the SELECT list."""
    return [e.alias_or_name for e in sqlglot.parse_one(sql, read="postgres").expressions]


def validate_plan(plan: SQLPlan) -> SQLPlan:
    """Return the plan if it is accepted, or raise SQLValidationError listing every problem found."""
    hits = check_sql(plan.sql, plan.params, row_limit=plan.row_limit, declared_tables=plan.tables)
    if hits:
        raise SQLValidationError(hits)
    return plan