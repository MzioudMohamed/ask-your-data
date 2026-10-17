-- Storage for the RAG index of the metrics glossary.
-- Re-runnable: nothing is dropped, so existing vectors are kept.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS rag;

CREATE TABLE IF NOT EXISTS rag.glossary_chunks (
    entry_id    text        NOT NULL,   -- glossary entry id, used as the citation (for example: revenue)
    model       text        NOT NULL,   -- embedding model that produced the vector
    content     text        NOT NULL,   -- the exact text that was embedded
    entry       jsonb       NOT NULL,   -- the full glossary entry (definition, sql, model, columns), returned with the citation
    embedding   vector      NOT NULL,   -- no fixed dimension: models with different sizes can coexist
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (entry_id, model)
);