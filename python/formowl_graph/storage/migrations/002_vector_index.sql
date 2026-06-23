-- FormOwl pgvector index contract migration.
--
-- This defines the production-facing vector-index table shape used by the
-- internal pgvector repository adapter. It is not a claim that the adapter has
-- been executed against a live PostgreSQL/pgvector service.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS formowl_vector_index (
    vector_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    embedding vector NOT NULL,
    permission_scope JSONB NOT NULL,
    index_state TEXT NOT NULL,
    embedding_manifest_hash TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_formowl_vector_index_state
    ON formowl_vector_index (index_state);

CREATE INDEX IF NOT EXISTS idx_formowl_vector_index_scope
    ON formowl_vector_index
    USING btree ((permission_scope->>'scope_type'), (permission_scope->>'scope_id'));
