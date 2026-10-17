import argparse

import psycopg
import yaml
from psycopg.types.json import Jsonb

from askdata import config
from askdata.rag.embeddings import embed


def load_entries():
    with open(config.GLOSSARY_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)["entries"]


def build_chunk_text(entry):
    """Text embedded for one glossary entry: names, synonyms, definitions, caveats, example questions."""
    lines = [
        f"{entry['name_en']} / {entry['name_fr']}",
        "Synonyms: " + ", ".join(entry["synonyms"]),
        "Definition (EN): " + " ".join(entry["definition_en"].split()),
        "Définition (FR): " + " ".join(entry["definition_fr"].split()),
    ]
    for caveat in entry.get("caveats", []):
        lines.append("Caveat: " + caveat)
    for question in entry.get("example_questions", []):
        lines.append("Example question: " + question)
    return "\n".join(lines)


def to_pgvector(vector):
    return "[" + ",".join(str(x) for x in vector) + "]"


def main():
    parser = argparse.ArgumentParser(description="Index the metrics glossary in pgvector.")
    parser.add_argument("--model", default=config.EMBEDDING_MODEL, help="Ollama embedding model name")
    args = parser.parse_args()

    entries = load_entries()
    chunks = [build_chunk_text(e) for e in entries]
    vectors = embed(chunks, model=args.model)
    if len(vectors) != len(entries):
        raise RuntimeError(f"Expected {len(entries)} embeddings, got {len(vectors)}")

    with psycopg.connect(**config.DB) as conn:
        with conn.cursor() as cur:
            for entry, chunk, vector in zip(entries, chunks, vectors):
                cur.execute(
                    """
                    INSERT INTO rag.glossary_chunks (entry_id, model, content, entry, embedding)
                    VALUES (%s, %s, %s, %s, %s::vector)
                    ON CONFLICT (entry_id, model) DO UPDATE
                    SET content = EXCLUDED.content,
                        entry = EXCLUDED.entry,
                        embedding = EXCLUDED.embedding,
                        created_at = now()
                    """,
                    (entry["id"], args.model, chunk, Jsonb(entry), to_pgvector(vector)),
                )
            # Remove vectors of entries that no longer exist in the glossary.
            cur.execute(
                "DELETE FROM rag.glossary_chunks WHERE model = %s AND entry_id <> ALL(%s)",
                (args.model, [e["id"] for e in entries]),
            )

    print(f"Indexed {len(entries)} entries with model {args.model} ({len(vectors[0])} dimensions)")


if __name__ == "__main__":
    main()