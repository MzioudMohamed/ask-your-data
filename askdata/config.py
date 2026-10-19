import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DB = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_USER", "askdata"),
    "password": os.getenv("POSTGRES_PASSWORD", "askdata_dev"),
    "dbname": os.getenv("POSTGRES_DB", "askdata"),
}

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "qwen3-embedding:0.6b")
GLOSSARY_PATH = PROJECT_ROOT / "glossary" / "metrics.yml"

QUERY_INSTRUCTION = (
    "Given a business question about e-commerce analytics, "
    "retrieve the glossary entry that defines the metric or concept the question asks about"
)

DB_READER = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_READER_USER", "askdata_reader"),
    "password": os.getenv("POSTGRES_READER_PASSWORD", "askdata_reader_dev"),
    "dbname": os.getenv("POSTGRES_DB", "askdata"),
}