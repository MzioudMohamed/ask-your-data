"""Thin client for the local language model served by Ollama.

Everything the copilot asks of the model goes through chat_json(): the answer is constrained to a JSON schema,
so the model can only produce text that has the shape of the schema. The result is validated again by Pydantic.
"""
import requests

from askdata import config

# These models "think" before answering unless told not to. Thinking is slow on a CPU and useless here.
THINKING_MODELS = ("qwen3",)


def inline_refs(schema):
    """Replace every $ref by the definition it points to and drop $defs: a flatter schema is easier for the model."""
    definitions = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                target = resolve(definitions[node["$ref"].split("/")[-1]])
                return {**target, **{k: resolve(v) for k, v in node.items() if k != "$ref"}}
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def chat_json(messages, schema, model=None, num_ctx=4096, max_tokens=400):
    """Ask the model for one JSON object matching the schema. Returns (text, stats)."""
    model = model or config.LLM_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": inline_refs(schema),
        "options": {"temperature": 0, "seed": 0, "num_ctx": num_ctx, "num_predict": max_tokens},
        "keep_alive": "10m",
    }
    if model.split(":")[0] in THINKING_MODELS:
        payload["think"] = False

    response = requests.post(f"{config.OLLAMA_URL}/api/chat", json=payload, timeout=900)
    response.raise_for_status()
    data = response.json()

    def seconds(key):
        return data.get(key, 0) / 1e9

    gen_seconds, prompt_seconds = seconds("eval_duration"), seconds("prompt_eval_duration")
    stats = {
        "total_s": seconds("total_duration"),
        "load_s": seconds("load_duration"),
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "prompt_s": prompt_seconds,
        "gen_tokens": data.get("eval_count", 0),
        "gen_s": gen_seconds,
        "gen_tokens_per_s": data.get("eval_count", 0) / gen_seconds if gen_seconds else 0.0,
    }
    return data["message"]["content"], stats