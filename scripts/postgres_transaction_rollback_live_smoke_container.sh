#!/usr/bin/env bash
set -euo pipefail

source /workspace/scripts/postgres_container_harness.sh

formowl_postgres_require_env FORMOWL_POSTGRES_ROLLBACK_LIVE_RUN_ID FORMOWL_POSTGRES_ROLLBACK_IMAGE FORMOWL_POSTGRES_ROLLBACK_RUNNER_SCRIPT_SHA256 FORMOWL_POSTGRES_ROLLBACK_CONTAINER_ENTRYPOINT_SHA256 FORMOWL_POSTGRES_ROLLBACK_MIGRATION_MANIFEST_SHA256

output_path="${1:?output path is required}"

formowl_postgres_initialize /tmp/formowl-main-repo-postgres-rollback-live-smoke /tmp/formowl-main-repo-postgres-rollback.log
formowl_postgres_apply_migration /workspace/python/formowl_graph/storage/migrations/001_metadata_store.sql

psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" <<'SQL'
INSERT INTO formowl_graph_records (
  record_id,
  record_type,
  workspace_id,
  permission_scope,
  payload,
  payload_hash
) VALUES (
  'commit_probe_graph_record',
  'candidate_atom',
  'workspace_main',
  '{"visibility":"restricted","scope_type":"project","scope_id":"project_formowl"}'::jsonb,
  '{"label":"committed metadata-store probe"}'::jsonb,
  'sha256:commit-probe'
);
SQL

set +e
psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$POSTGRES_DB" <<'SQL'
BEGIN;
INSERT INTO formowl_graph_records (
  record_id,
  record_type,
  workspace_id,
  permission_scope,
  payload,
  payload_hash
) VALUES (
  'rollback_probe_graph_record',
  'candidate_atom',
  'workspace_main',
  '{"visibility":"restricted","scope_type":"project","scope_id":"project_formowl"}'::jsonb,
  '{"label":"rollback metadata-store probe"}'::jsonb,
  'sha256:rollback-probe'
);
INSERT INTO formowl_audit_log (
  audit_log_id,
  actor_user_id,
  action,
  target_type,
  target_id,
  session_id,
  workspace_id,
  status,
  metadata,
  timestamp
) VALUES (
  'rollback_probe_audit',
  'user_reviewer',
  'rollback_probe',
  'candidate_atom',
  'rollback_probe_graph_record',
  'session_rollback_probe',
  'workspace_main',
  'started',
  '{"probe":"metadata-store rollback"}'::jsonb,
  '2026-06-21T00:00:00+00:00'::timestamptz
);
INSERT INTO formowl_graph_records (
  record_id,
  record_type,
  workspace_id,
  permission_scope,
  payload,
  payload_hash
) VALUES (
  'rollback_probe_graph_record',
  'candidate_atom',
  'workspace_main',
  '{"visibility":"restricted","scope_type":"project","scope_id":"project_formowl"}'::jsonb,
  '{"label":"duplicate should fail"}'::jsonb,
  'sha256:rollback-duplicate'
);
COMMIT;
SQL
rollback_failure_exit_code="$?"
set -e

psql -v ON_ERROR_STOP=1 \
  -v FORMOWL_POSTGRES_ROLLBACK_LIVE_RUN_ID="$FORMOWL_POSTGRES_ROLLBACK_LIVE_RUN_ID" \
  -v FORMOWL_POSTGRES_ROLLBACK_IMAGE="$FORMOWL_POSTGRES_ROLLBACK_IMAGE" \
  -v FORMOWL_POSTGRES_ROLLBACK_RUNNER_SCRIPT_SHA256="$FORMOWL_POSTGRES_ROLLBACK_RUNNER_SCRIPT_SHA256" \
  -v FORMOWL_POSTGRES_ROLLBACK_CONTAINER_ENTRYPOINT_SHA256="$FORMOWL_POSTGRES_ROLLBACK_CONTAINER_ENTRYPOINT_SHA256" \
  -v FORMOWL_POSTGRES_ROLLBACK_MIGRATION_MANIFEST_SHA256="$FORMOWL_POSTGRES_ROLLBACK_MIGRATION_MANIFEST_SHA256" \
  -v ROLLBACK_FAILURE_EXIT_CODE="$rollback_failure_exit_code" \
  -v OUTPUT_PATH="$output_path" \
  -U "$PGUSER" \
  -d "$POSTGRES_DB" <<'SQL'
CREATE TEMP TABLE formowl_rollback_smoke_counts AS
SELECT
  (
    SELECT count(*)
    FROM formowl_graph_records
    WHERE record_id = 'commit_probe_graph_record'
  ) AS committed_graph_record_count,
  (
    SELECT count(*)
    FROM formowl_graph_records
    WHERE record_id = 'rollback_probe_graph_record'
  ) AS rolled_back_graph_record_count,
  (
    SELECT count(*)
    FROM formowl_audit_log
    WHERE audit_log_id = 'rollback_probe_audit'
  ) AS rolled_back_audit_log_count;

\pset tuples_only on
\pset format unaligned
\o :OUTPUT_PATH
SELECT jsonb_pretty(
  jsonb_build_object(
      'artifact_id', 'main_repo_postgres_transaction_rollback_live_smoke_v1',
      'run_id', :'FORMOWL_POSTGRES_ROLLBACK_LIVE_RUN_ID',
      'image_reference', :'FORMOWL_POSTGRES_ROLLBACK_IMAGE',
      'runner_script_sha256', :'FORMOWL_POSTGRES_ROLLBACK_RUNNER_SCRIPT_SHA256',
      'container_entrypoint_sha256', :'FORMOWL_POSTGRES_ROLLBACK_CONTAINER_ENTRYPOINT_SHA256',
      'repo_reference', 'main_repo_workspace',
      'repo_path_redacted', true,
      'postgres_version', current_setting('server_version'),
      'migration_files_applied', jsonb_build_array('001_metadata_store.sql'),
      'migration_manifest_sha256', :'FORMOWL_POSTGRES_ROLLBACK_MIGRATION_MANIFEST_SHA256',
      'safe_outputs', jsonb_build_object(
        'committed_graph_record_count', (
          SELECT committed_graph_record_count FROM formowl_rollback_smoke_counts
        ),
        'rolled_back_graph_record_count', (
          SELECT rolled_back_graph_record_count FROM formowl_rollback_smoke_counts
        ),
        'rolled_back_audit_log_count', (
          SELECT rolled_back_audit_log_count FROM formowl_rollback_smoke_counts
        )
      ),
      'metrics', jsonb_build_object(
        'live_postgres_transaction_rollback_smoke_executed', true,
        'metadata_migration_applied', EXISTS (
          SELECT 1 FROM pg_tables
          WHERE schemaname = 'public'
            AND tablename = 'formowl_graph_records'
        ),
        'transactional_commit_persisted', (
          SELECT committed_graph_record_count FROM formowl_rollback_smoke_counts
        ) = 1,
        'partial_failure_error_observed', :'ROLLBACK_FAILURE_EXIT_CODE'::int <> 0,
        'partial_failure_transaction_rolled_back', (
          SELECT rolled_back_graph_record_count FROM formowl_rollback_smoke_counts
        ) = 0,
        'graph_record_rollback_verified', (
          SELECT rolled_back_graph_record_count FROM formowl_rollback_smoke_counts
        ) = 0,
        'audit_log_rollback_verified', (
          SELECT rolled_back_audit_log_count FROM formowl_rollback_smoke_counts
        ) = 0,
        'canonical_graph_writes', false,
        'raw_access_expanded', false,
        'raw_sql_exposed', false,
        'raw_storage_path_exposed', false
      ),
      'claim_boundary', jsonb_build_object(
        'supports_main_repo_postgres_transaction_rollback_claim', true,
        'supports_live_postgresql_metadata_store_rollback_claim', true,
        'supports_production_adapter_ready_claim', false,
        'supports_end_to_end_gateway_claim', false,
        'supports_canonical_graph_write_claim', false
      )
  )
);
\o
SQL
