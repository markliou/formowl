-- Issue #51 WP1 source-neutral evidence coverage and claim contracts.
--
-- This additive migration stores immutable contract payloads beside the
-- existing normalized mail evidence rows.  It intentionally does not alter
-- migration 005, which is owned by the OAuth branch.

CREATE TABLE IF NOT EXISTS source_inventory_item (
  source_inventory_item_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS structural_observation (
  structural_observation_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim_requirement (
  claim_requirement_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  query_id text NOT NULL,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS coverage_ledger (
  coverage_ledger_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  query_id text NOT NULL,
  claim_requirement_id text NOT NULL,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS answer_claim (
  answer_claim_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  claim_requirement_id text NOT NULL,
  coverage_ledger_id text NOT NULL,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS version_manifest (
  version_manifest_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_inventory_item_import
  ON source_inventory_item (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_structural_observation_import
  ON structural_observation (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_claim_requirement_query
  ON claim_requirement (mail_import_session_id, query_id);
CREATE INDEX IF NOT EXISTS idx_coverage_ledger_query
  ON coverage_ledger (mail_import_session_id, query_id, claim_requirement_id);
CREATE INDEX IF NOT EXISTS idx_answer_claim_ledger
  ON answer_claim (mail_import_session_id, coverage_ledger_id);
CREATE INDEX IF NOT EXISTS idx_version_manifest_import
  ON version_manifest (mail_import_session_id);
