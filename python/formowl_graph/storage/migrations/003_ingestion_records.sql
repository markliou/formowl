-- FormOwl ingestion-record database-store contract migration.
--
-- This table stores validated ingestion contract payloads behind the same
-- create/get/list surface as the file-backed ingestion stores. It is an
-- internal metadata table, not a ChatGPT-facing raw storage surface.

CREATE TABLE IF NOT EXISTS formowl_ingestion_records (
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    permission_scope JSONB NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (record_type, record_id)
);

CREATE INDEX IF NOT EXISTS idx_formowl_ingestion_records_scope
    ON formowl_ingestion_records
    USING btree (record_type, (permission_scope->>'scope_type'), (permission_scope->>'scope_id'));

CREATE INDEX IF NOT EXISTS idx_formowl_ingestion_records_asset
    ON formowl_ingestion_records
    USING btree (record_type, (payload->>'asset_id'));
