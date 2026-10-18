import argparse

import psycopg

from askdata import config
from askdata.rag.embeddings import embed, to_pgvector


def format_query(question, model):
    """Qwen3 embedding models expect a task instruction in front of the query. Documents get none."""
    if model.startswith("qwen3-embedding"):
        return f"Instruct: {config.QUERY_INSTRUCTION}\nQuery:{question}"
    return question


def retrieve(question, k=3, model=None):
    """Return the k glossary entries closest to the question, with their cosine similarity."""
    model = model or config.EMBEDDING_MODEL
    vector = to_pgvector(embed([format_query(question, model)], model=model)[0])
    with psycopg.connect(**config.DB) as conn:
        rows = conn.execute(
            """
            SELECT entry_id, entry, 1 - (embedding <=> %s::vector) AS similarity
            FROM rag.glossary_chunks
            WHERE model = %s
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (vector, model, vector, k),
        ).fetchall()
    return [{"entry_id": r[0], "similarity": float(r[2]), "entry": r[1]} for r in rows]


def main():
    parser = argparse.ArgumentParser(description="Search the metrics glossary.")
    parser.add_argument("question")
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--model", default=config.EMBEDDING_MODEL)
    args = parser.parse_args()

    print(f"Q: {args.question}")
    for rank, hit in enumerate(retrieve(args.question, k=args.k, model=args.model), start=1):
        e = hit["entry"]
        print(f"  {rank}. {hit['entry_id']:<22} {hit['similarity']:.3f}  "
              f"{e['name_en']} / {e['name_fr']}  ({e.get('model', '-')})")


if __name__ == "__main__":
    main()