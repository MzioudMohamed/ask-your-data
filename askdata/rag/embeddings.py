import requests

from askdata import config

# Some embedding models expect a different prefix for queries and for documents.
# The prefixes come from each model's documentation. A model not listed gets no prefix.
PROFILES = {
    "qwen3-embedding": {
        "query": f"Instruct: {config.QUERY_INSTRUCTION}\nQuery:",
        "document": "",
    },
    "embeddinggemma": {
        "query": "task: search result | query: ",
        "document": "title: none | text: ",
    },
    "bge-m3": {"query": "", "document": ""},
}


def _profile(model):
    return PROFILES.get(model.split(":")[0], {"query": "", "document": ""})


def format_query(question, model):
    return _profile(model)["query"] + question


def format_document(text, model):
    return _profile(model)["document"] + text


def embed(texts, model=None):
    """Return one embedding (a list of floats) per text, computed locally by Ollama."""
    model = model or config.EMBEDDING_MODEL
    response = requests.post(
        f"{config.OLLAMA_URL}/api/embed",
        json={"model": model, "input": texts},
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["embeddings"]


def to_pgvector(vector):
    """Format a list of floats as a pgvector literal, for example [0.1,0.2]."""
    return "[" + ",".join(str(x) for x in vector) + "]"