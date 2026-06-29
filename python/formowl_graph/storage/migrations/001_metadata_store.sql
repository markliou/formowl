-- FormOwl metadata-store contract migration.
--
-- This migration is intentionally narrow: it defines the production-facing
-- table and index contract used by the PostgreSQL repository adapter. It is not
-- a claim that the adapter has been executed against a live PostgreSQL server.

CREATE TABLE IF NOT EXISTS formowl_graph_records (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    permission_scope JSONB NOT NULL,
    payload JSONB NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS formowl_review_decisions (
    review_decision_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    audit_log_id TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS formowl_canonical_commit_proposals (
    canonical_commit_proposal_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    candidate_atom_ids TEXT[] NOT NULL DEFAULT '{}',
    candidate_relation_ids TEXT[] NOT NULL DEFAULT '{}',
    required_review_decision_ids TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS formowl_user_graph_revisions (
    user_graph_revision_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    graph_revision_id TEXT NOT NULL,
    ontology_revision_id TEXT NOT NULL,
    visible_canonical_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS formowl_grants (
    grant_id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    grantee_user_id TEXT NOT NULL,
    scope_type TEXT NOT NULL,
    scope_id TEXT NOT NULL,
    permission TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS formowl_audit_log (
    audit_log_id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    workspace_id TEXT,
    status TEXT,
    metadata JSONB,
    timestamp TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_formowl_graph_records_scope
    ON formowl_graph_records
    USING btree ((permission_scope->>'scope_type'), (permission_scope->>'scope_id'));

CREATE INDEX IF NOT EXISTS idx_formowl_grants_effective_scope
    ON formowl_grants (grantee_user_id, scope_type, scope_id, permission, expires_at)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_formowl_audit_log_actor_target
    ON formowl_audit_log (actor_user_id, target_type, target_id, timestamp);
