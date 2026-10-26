"""Prompts sent to the language model. The metric list is read from the glossary, so it cannot drift from it."""
import json

from askdata import glossary

# The data ends here: relative dates ("last year", "last month") are computed from this date, not from today.
REFERENCE_DATE = "2018-10-17"

RULES = f"""You convert a business question about an e-commerce dataset into one JSON object that follows the given schema.
Reply with the JSON object only. The question may be in French or English.

Rules:
- "metrics": ids from the list below, never anything else. Pick the metric(s) the question asks about.
- "dimensions": categorical breakdowns. "by state" -> customer_state, "by product category" -> product_category, "by seller state" -> seller_state, "by order status" -> order_status. Use only the breakdowns allowed for the metric.
- "time_grain": "month" for monthly or per-month questions, "year" for yearly ones, otherwise leave it out.
- "date_from" and "date_to": ISO dates, both inclusive. "in 2017" means 2017-01-01 to 2017-12-31. The data ends on {REFERENCE_DATE}: compute relative expressions such as "last year" or "last month" from that date, not from today.
- "window_days": 90 or 180, only for repurchase_rate.
- "top_k": an integer when the question asks for the top, best, highest or lowest N. "sort" is "desc" by default and "asc" for the lowest or slowest-to-fix cases.
- "filters": restrict a breakdown to some values, for example {{"dimension": "customer_state", "op": "in", "values": ["SP"]}}. Brazilian states use their two-letter code.
- "confidence": between 0 and 1. If the question is ambiguous, lower it and put one short question in "clarification".
"""

EXAMPLES = [
    ("Montant des ventes par catégorie de produit en 2018",
     {"metrics": ["revenue"], "dimensions": ["product_category"], "date_from": "2018-01-01",
      "date_to": "2018-12-31", "confidence": 0.9}),
    ("Which 3 states have the slowest delivery?",
     {"metrics": ["delivery_time"], "dimensions": ["customer_state"], "top_k": 3, "sort": "desc",
      "confidence": 0.9}),
    ("How did the share of customers who buy again within 90 days evolve by cohort?",
     {"metrics": ["repurchase_rate"], "time_grain": "month", "window_days": 90, "confidence": 0.85}),
]


def _first_sentence(text, limit=220):
    text = " ".join(text.split())
    return (text.split(". ")[0].rstrip(".") + ".")[:limit]


def metrics_block():
    lines = []
    for metric_id, entry in glossary.metrics().items():
        dims = ", ".join(sorted(glossary.allowed_dimensions(metric_id))) or "none"
        lines.append(f"- {metric_id}: {_first_sentence(entry['definition_en'])} Breakdowns: {dims}.")
    return "\n".join(lines)


def system_prompt():
    """Static part (rules, metrics, examples): identical for every question, so the model can reuse its cache."""
    examples = "\n".join(
        f"Question: {q}\nJSON: {json.dumps(answer, ensure_ascii=False)}" for q, answer in EXAMPLES
    )
    return f"{RULES}\nMetrics:\n{metrics_block()}\n\nExamples:\n{examples}"


def build_intent_messages(question, hits=None):
    """Chat messages for the intent extraction. hits are glossary entries retrieved for the question (RAG)."""
    user = ""
    if hits:
        context = "\n".join(
            f"- {h['entry_id']}: {' '.join(h['entry']['definition_en'].split())}" for h in hits
        )
        user += f"Glossary entries closest to the question:\n{context}\n\n"
    user += f"Question: {question}\nJSON:"
    return [{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}]