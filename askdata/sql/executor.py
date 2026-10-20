"""Run a validated SQLPlan with the read-only role and check what comes back."""
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import psycopg

from askdata import config
from askdata.schemas import Intent, SQLPlan
from askdata.sql.templates import build_plan
from askdata.sql.validator import expected_columns, validate_plan


class ExecutionError(Exception):
    """The query was accepted by the validator but failed or returned something unexpected.

    kind is one of: timeout, privilege, database, result_mismatch.
    """

    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(f"{kind}: {message}")


def _canonical(value):
    """Exact, stable text form of a value (used for the result hash)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def json_safe(value):
    """Form of a value that can be sent to the interface as JSON."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


@dataclass
class QueryResult:
    columns: list
    rows: list
    result_hash: str
    elapsed_ms: float

    @property
    def row_count(self):
        return len(self.rows)

    def preview(self, limit=100):
        """First rows in a JSON-friendly form, for the interface."""
        return [[json_safe(v) for v in row] for row in self.rows[:limit]]


def execute(plan: SQLPlan) -> QueryResult:
    plan = validate_plan(plan)  # raises SQLValidationError: nothing reaches the database in that case
    expected = expected_columns(plan.sql)

    started = time.perf_counter()
    try:
        with psycopg.connect(**config.DB_READER, autocommit=True) as conn:
            cursor = conn.execute(plan.sql, plan.params)
            columns = [c.name for c in cursor.description]
            rows = cursor.fetchall()
    except psycopg.errors.QueryCanceled:
        raise ExecutionError("timeout", "the query took too long and was stopped") from None
    except psycopg.errors.InsufficientPrivilege as error:
        raise ExecutionError("privilege", str(error).splitlines()[0]) from None
    except psycopg.Error as error:
        raise ExecutionError("database", str(error).splitlines()[0]) from None
    elapsed_ms = (time.perf_counter() - started) * 1000

    if columns != expected:
        raise ExecutionError("result_mismatch", f"expected columns {expected}, got {columns}")
    if len(rows) > plan.row_limit:
        raise ExecutionError("result_mismatch", f"{len(rows)} rows returned, limit is {plan.row_limit}")

    payload = json.dumps(
        {"columns": columns, "rows": [[_canonical(v) for v in row] for row in rows]},
        sort_keys=True, default=str,
    )
    return QueryResult(
        columns=columns,
        rows=[tuple(row) for row in rows],
        result_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        elapsed_ms=elapsed_ms,
    )


def run_intent(intent: Intent):
    """Intent to plan to result. Returns (plan, result)."""
    plan = build_plan(intent)
    return plan, execute(plan)