import requests

from askdata import config


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