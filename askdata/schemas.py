"""Shared vocabulary of the copilot: what the agents exchange.

Intent   : what the user asks, in structured form (produced by the LLM, then validated here).
SQLPlan  : the SQL that will run, built by deterministic code from an Intent (never written by the LLM).
Answer   : what the API returns to the interface.
"""
import hashlib
import json
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from askdata import config, glossary

# These lists must match glossary/metrics.yml: tests/test_schemas.py fails if they drift apart.
MetricId = Literal[
    "revenue",
    "orders_count",
    "average_basket",
    "delivery_time",
    "late_delivery_rate",
    "average_review_score",
    "repurchase_rate",
]
Dimension = Literal["customer_state", "product_category", "seller_state", "order_status"]
TimeGrain = Literal["month", "year"]

# Letters, digits, underscore, space and hyphen only: no quote, semicolon or comment marker.
SAFE_VALUE = re.compile(r"^[A-Za-z0-9_ \-]{1,60}$")


class Strict(BaseModel):
    """Base class: unknown fields are rejected, so nothing unexpected (for example SQL) can slip in."""

    model_config = ConfigDict(extra="forbid")


class Filter(Strict):
    dimension: Dimension
    op: Literal["in", "not_in"] = "in"
    values: list[str] = Field(min_length=1, max_length=50)

    @field_validator("values")
    @classmethod
    def values_are_safe(cls, values):
        for value in values:
            if not SAFE_VALUE.match(value):
                raise ValueError(f"unsafe filter value: {value!r}")
        return values


class Intent(Strict):
    metrics: list[MetricId] = Field(min_length=1, max_length=3)
    dimensions: list[Dimension] = Field(default_factory=list, max_length=2)
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    time_grain: TimeGrain | None = None          # None means no breakdown over time
    date_from: date | None = None                # inclusive
    date_to: date | None = None                  # inclusive
    window_days: Literal[90, 180] | None = None  # repurchase window, only for repurchase_rate
    top_k: int | None = Field(default=None, ge=1, le=50)
    sort: Literal["desc", "asc"] = "desc"
    confidence: float = Field(ge=0.0, le=1.0)
    clarification: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def check_against_the_glossary(self):
        if len(set(self.metrics)) != len(self.metrics):
            raise ValueError("metrics must be unique")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("dimensions must be unique")

        sources = {glossary.source_model(m) for m in self.metrics}
        if len(sources) > 1:
            raise ValueError(f"metrics come from different tables and cannot be combined: {sorted(sources)}")

        used = list(self.dimensions) + [f.dimension for f in self.filters]
        for metric in self.metrics:
            allowed = glossary.allowed_dimensions(metric)
            for dimension in used:
                if dimension not in allowed:
                    raise ValueError(f"{metric} cannot be broken down or filtered by {dimension}")

        if self.window_days is not None and "repurchase_rate" not in self.metrics:
            raise ValueError("window_days only applies to repurchase_rate")
        if self.top_k is not None and not self.dimensions:
            raise ValueError("top_k needs at least one dimension to rank")
        if self.top_k is not None and self.time_grain is not None:
            raise ValueError("top_k cannot be combined with time_grain")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        return self

    @property
    def needs_clarification(self):
        """True when the system should ask the user instead of answering."""
        return self.clarification is not None or self.confidence < config.MIN_CONFIDENCE


class SQLPlan(Strict):
    template_id: str
    sql: str                                  # parameterized text, values are never pasted into it
    params: dict[str, Any] = Field(default_factory=dict)
    row_limit: int = Field(ge=1, le=1000)
    denylist_hits: list[str] = Field(default_factory=list)  # forbidden patterns found by the validator
    tables: list[str] = Field(default_factory=list)         # tables read by the query, found by the validator

    @model_validator(mode="before")
    @classmethod
    def drop_serialized_hash(cls, data):
        """plan_hash is computed, so a serialized plan can be loaded back: its stored hash is ignored."""
        if isinstance(data, dict):
            data = {key: value for key, value in data.items() if key != "plan_hash"}
        return data

    @computed_field
    @property
    def plan_hash(self) -> str:
        """Fingerprint of the plan, for traceability and tests."""
        payload = json.dumps(
            {"template_id": self.template_id, "sql": self.sql, "params": self.params, "row_limit": self.row_limit},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Citation(Strict):
    entry_id: str                  # glossary entry id, for example: revenue
    name: str
    model: str | None = None       # dbt model the metric is computed from
    similarity: float


class Answer(Strict):
    question: str
    status: Literal["answered", "definition", "needs_clarification", "unsupported", "error"]
    intent: Intent | None = None
    sql_plan: SQLPlan | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list, max_length=100)  # table preview, 100 rows at most
    row_count: int | None = None
    result_hash: str | None = None
    chart_spec: dict[str, Any] | None = None
    narrative: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    clarification: str | None = None
    errors: list[str] = Field(default_factory=list)
    retries: int = Field(default=0, ge=0, le=5)
    timings_ms: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_status_rules(self):
        if self.status == "answered":
            if self.sql_plan is None or not self.narrative:
                raise ValueError("an answered question needs a sql_plan and a narrative")
            if not self.citations:
                raise ValueError("an answered question must cite at least one glossary entry")
        elif self.status == "definition":
            if not self.narrative or not self.citations:
                raise ValueError("a definition needs a narrative and at least one citation")
        elif self.status == "needs_clarification":
            if not self.clarification:
                raise ValueError("needs_clarification requires a clarification question")
        elif self.status == "unsupported":
            if not self.narrative:
                raise ValueError("unsupported requires a narrative that explains why")
        elif self.status == "error":
            if not self.errors:
                raise ValueError("error requires at least one error message")
        return self