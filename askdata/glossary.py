from functools import lru_cache

import yaml

from askdata import config

TIME_COLUMNS = {"purchase_month", "cohort_month"}


def load_entries():
    with open(config.GLOSSARY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["entries"]


@lru_cache(maxsize=1)
def metrics():
    """Glossary entries of type metric, by id."""
    return {e["id"]: e for e in load_entries() if e["type"] == "metric"}


def allowed_dimensions(metric_id):
    """Categorical dimensions a metric can be broken down or filtered by.
    Time columns are handled separately by time_grain."""
    entry = metrics()[metric_id]
    dims = set(entry.get("dimensions", [])) | set(entry.get("alt_dimensions", []))
    return dims - TIME_COLUMNS


def source_model(metric_id):
    """The dbt model a metric is computed from."""
    return metrics()[metric_id]["model"]