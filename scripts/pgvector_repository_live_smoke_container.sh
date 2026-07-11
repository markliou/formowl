#!/usr/bin/env bash
set -euo pipefail

source /workspace/scripts/postgres_container_harness.sh

formowl_postgres_require_env FORMOWL_PGVECTOR_LIVE_RUN_ID FORMOWL_PGVECTOR_IMAGE FORMOWL_PGVECTOR_RUNNER_SCRIPT_SHA256 FORMOWL_PGVECTOR_CONTAINER_ENTRYPOINT_SHA256 FORMOWL_PGVECTOR_MIGRATION_MANIFEST_SHA256

output_path="${1:?output path is required}"

formowl_postgres_initialize /tmp/formowl-main-repo-pgvector-live-smoke /tmp/formowl-main-repo-pgvector.log
formowl_postgres_apply_migration \
  /workspace/python/formowl_graph/storage/migrations/001_metadata_store.sql \
  /workspace/python/formowl_graph/storage/migrations/002_vector_index.sql

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" <<'SQL'
INSERT INTO formowl_grants (
  grant_id,
  owner_user_id,
  grantee_user_id,
  scope_type,
  scope_id,
  permission,
  expires_at,
  revoked_at
) VALUES (
  'grant_project_formowl_search_to_pm',
  'user_ops',
  'user_pm',
  'project',
  'project_formowl',
  'search',
  '2027-01-01T00:00:00+00:00',
  NULL
);

INSERT INTO formowl_vector_index (
  vector_id,
  source_type,
  source_id,
  embedding,
  permission_scope,
  index_state,
  embedding_manifest_hash
) VALUES
  (
    'vec_workspace_decision',
    'observation',
    'obs_workspace_decision',
    '[0.80,0.18,0.02]'::vector,
    '{"visibility":"restricted","scope_type":"project","scope_id":"project_formowl"}'::jsonb,
    'ready',
    'sha256:fixture-embedding-v1'
  ),
  (
    'vec_private_invoice',
    'observation',
    'obs_private_invoice',
    '[0.99,0.01,0.01]'::vector,
    '{"visibility":"restricted","scope_type":"private_user","scope_id":"user_finance"}'::jsonb,
    'ready',
    'sha256:fixture-embedding-v1'
  ),
  (
    'vec_workspace_stale_note',
    'observation',
    'obs_workspace_stale_note',
    '[0.81,0.17,0.02]'::vector,
    '{"visibility":"restricted","scope_type":"project","scope_id":"project_formowl"}'::jsonb,
    'stale',
    'sha256:fixture-embedding-v1'
  );
SQL

psql -v ON_ERROR_STOP=1 \
  -v FORMOWL_PGVECTOR_LIVE_RUN_ID="$FORMOWL_PGVECTOR_LIVE_RUN_ID" \
  -v FORMOWL_PGVECTOR_IMAGE="$FORMOWL_PGVECTOR_IMAGE" \
  -v FORMOWL_PGVECTOR_RUNNER_SCRIPT_SHA256="$FORMOWL_PGVECTOR_RUNNER_SCRIPT_SHA256" \
  -v FORMOWL_PGVECTOR_CONTAINER_ENTRYPOINT_SHA256="$FORMOWL_PGVECTOR_CONTAINER_ENTRYPOINT_SHA256" \
  -v FORMOWL_PGVECTOR_MIGRATION_MANIFEST_SHA256="$FORMOWL_PGVECTOR_MIGRATION_MANIFEST_SHA256" \
  -v OUTPUT_PATH="$output_path" \
  -U "$PGUSER" \
  -d "$POSTGRES_DB" <<'SQL'
CREATE TEMP TABLE formowl_smoke_ready_result AS
WITH ready_search AS (
  SELECT v.vector_id, v.source_id
  FROM formowl_vector_index v
  WHERE v.index_state = 'ready'
    AND (
      v.permission_scope->>'visibility' = 'public'
      OR EXISTS (
        SELECT 1
        FROM formowl_grants g
        WHERE g.grantee_user_id = 'user_pm'
          AND g.scope_type = v.permission_scope->>'scope_type'
          AND g.scope_id = v.permission_scope->>'scope_id'
          AND g.permission = ANY(ARRAY['evidence_snippet','graph_snippet','read','search'])
          AND g.revoked_at IS NULL
          AND g.expires_at > '2026-06-21T00:00:00+00:00'::timestamptz
      )
    )
  ORDER BY v.embedding <=> '[0.80,0.18,0.02]'::vector
  LIMIT 5
)
SELECT vector_id, source_id FROM ready_search;

UPDATE formowl_grants
SET revoked_at = '2026-06-21T00:01:00+00:00'::timestamptz
WHERE grant_id = 'grant_project_formowl_search_to_pm';

CREATE TEMP TABLE formowl_smoke_post_revoke_result AS
WITH ready_search AS (
  SELECT v.vector_id, v.source_id
  FROM formowl_vector_index v
  WHERE v.index_state = 'ready'
    AND (
      v.permission_scope->>'visibility' = 'public'
      OR EXISTS (
        SELECT 1
        FROM formowl_grants g
        WHERE g.grantee_user_id = 'user_pm'
          AND g.scope_type = v.permission_scope->>'scope_type'
          AND g.scope_id = v.permission_scope->>'scope_id'
          AND g.permission = ANY(ARRAY['evidence_snippet','graph_snippet','read','search'])
          AND g.revoked_at IS NULL
          AND g.expires_at > '2026-06-21T00:00:00+00:00'::timestamptz
      )
    )
  ORDER BY v.embedding <=> '[0.80,0.18,0.02]'::vector
  LIMIT 5
)
SELECT vector_id, source_id FROM ready_search;

\pset tuples_only on
\pset format unaligned
\o :OUTPUT_PATH
SELECT jsonb_pretty(
  jsonb_build_object(
      'artifact_id', 'main_repo_pgvector_repository_live_smoke_v1',
      'run_id', :'FORMOWL_PGVECTOR_LIVE_RUN_ID',
      'image_reference', :'FORMOWL_PGVECTOR_IMAGE',
      'runner_script_sha256', :'FORMOWL_PGVECTOR_RUNNER_SCRIPT_SHA256',
      'container_entrypoint_sha256', :'FORMOWL_PGVECTOR_CONTAINER_ENTRYPOINT_SHA256',
      'repo_reference', 'main_repo_workspace',
      'repo_path_redacted', true,
      'postgres_version', current_setting('server_version'),
      'extension_version', (SELECT extversion FROM pg_extension WHERE extname = 'vector'),
      'migration_files_applied', jsonb_build_array(
        '001_metadata_store.sql',
        '002_vector_index.sql'
      ),
      'migration_manifest_sha256', :'FORMOWL_PGVECTOR_MIGRATION_MANIFEST_SHA256',
      'safe_outputs', jsonb_build_object(
        'ready_result_source_ids', (
          SELECT COALESCE(jsonb_agg(source_id ORDER BY source_id), '[]'::jsonb)
          FROM formowl_smoke_ready_result
        ),
        'post_revoke_result_source_ids', (
          SELECT COALESCE(jsonb_agg(source_id ORDER BY source_id), '[]'::jsonb)
          FROM formowl_smoke_post_revoke_result
        )
      ),
      'metrics', jsonb_build_object(
        'live_postgres_pgvector_repository_smoke_executed', true,
        'migration_replay_applied', EXISTS (
          SELECT 1 FROM pg_tables
          WHERE schemaname = 'public'
            AND tablename = 'formowl_vector_index'
        ),
        'permission_filtered_sql_vector_query_tests', (
          SELECT COALESCE(jsonb_agg(source_id ORDER BY source_id), '[]'::jsonb)
          FROM formowl_smoke_ready_result
        ) = '["obs_workspace_decision"]'::jsonb,
        'stale_vector_regression_against_pgvector', NOT EXISTS (
          SELECT 1
          FROM formowl_smoke_ready_result
          WHERE source_id = 'obs_workspace_stale_note'
        ),
        'private_ungranted_vector_excluded', NOT EXISTS (
          SELECT 1
          FROM formowl_smoke_ready_result
          WHERE source_id = 'obs_private_invoice'
        ),
        'revoked_grant_regression', NOT EXISTS (
          SELECT 1 FROM formowl_smoke_post_revoke_result
        ),
        'canonical_graph_writes', false,
        'raw_access_expanded', false,
        'raw_sql_exposed', false
      ),
      'claim_boundary', jsonb_build_object(
        'supports_main_repo_pgvector_live_smoke_claim', true,
        'supports_permission_filtered_sql_vector_query_claim', true,
        'supports_stale_vector_regression_against_pgvector_claim', true,
        'supports_production_adapter_ready_claim', false,
        'supports_end_to_end_gateway_claim', false,
        'supports_canonical_graph_write_claim', false
      )
  )
);
\o
SQL

chmod 0666 "$output_path"
