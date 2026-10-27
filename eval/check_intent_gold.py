"""Check the intent gold set: valid format, no overlap with prompt examples, and every reference intent runs."""
import collections

import yaml

from askdata import config, glossary
from askdata.prompts import EXAMPLES
from askdata.schemas import Intent
from askdata.sql.executor import run_intent

GOLD_PATH = config.PROJECT_ROOT / "eval" / "intent_gold.yml"
STATUSES = {"answered", "definition", "unsupported", "needs_clarification"}


def load_gold():
    with open(GOLD_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["questions"]


def reference_intent(question):
    """The Intent a perfect system would produce for an answered question."""
    return Intent(confidence=1.0, **question["expected"])


def main():
    gold = load_gold()
    problems = []

    ids = [q["id"] for q in gold]
    if len(ids) != len(set(ids)):
        problems.append("duplicate ids")
    entries = {e["id"]: e for e in glossary.load_entries()}
    forbidden = {q.casefold() for q, _ in EXAMPLES}
    forbidden |= {x.casefold() for e in entries.values() for x in e.get("example_questions", [])}

    empty = []
    for q in gold:
        if q["status"] not in STATUSES:
            problems.append(f"{q['id']}: unknown status {q['status']}")
        if q["text"].casefold() in forbidden:
            problems.append(f"{q['id']}: same text as a prompt or glossary example")
        if q["status"] == "answered":
            try:
                _, result = run_intent(reference_intent(q))
            except Exception as exc:
                problems.append(f"{q['id']}: reference intent fails: {str(exc)[:120]}")
                continue
            if result.row_count == 0:
                empty.append(q["id"])
        elif q["status"] in ("definition", "unsupported") and q.get("cites"):
            wanted = {"definition": "concept", "unsupported": "unsupported"}[q["status"]]
            if entries.get(q["cites"], {}).get("type") != wanted:
                problems.append(f"{q['id']}: {q['cites']} is not a glossary entry of type {wanted}")

    print(f"{len(gold)} questions")
    print("status:", dict(collections.Counter(q["status"] for q in gold)))
    print("split: ", dict(collections.Counter(q["split"] for q in gold)))
    print("lang:  ", dict(collections.Counter(q["lang"] for q in gold)), "| hard:", sum(bool(q.get("hard")) for q in gold))
    print("reference intents with an empty result:", empty or "none")
    print("problems:", problems or "none")


if __name__ == "__main__":
    main()