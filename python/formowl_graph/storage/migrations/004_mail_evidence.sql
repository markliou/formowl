-- FormOwl Phase 1 normalized mail-evidence contract migration.
--
-- This migration defines the database-side mail evidence row shape used after
-- PST/OST/MSG/EML import. Raw archives and attachment bytes stay in object
-- storage or retention-controlled staging; PostgreSQL stores normalized
-- evidence records and lineage needed by governed MCP queries.

CREATE TABLE IF NOT EXISTS mail_import_session (
  mail_import_session_id text PRIMARY KEY,
  mail_evidence_bundle_id text NOT NULL UNIQUE,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  source_asset_id text NOT NULL,
  upload_session_id text,
  archive_sha256 text NOT NULL,
  retention_policy text NOT NULL,
  raw_archive_retention_decision text NOT NULL,
  producer_type text NOT NULL,
  status text NOT NULL,
  bundle_created_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mail_archive_occurrence (
  mail_archive_occurrence_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mail_folder_occurrence (
  mail_folder_occurrence_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_message (
  email_message_id text PRIMARY KEY,
  message_fingerprint text NOT NULL,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_message_occurrence (
  email_message_occurrence_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_body_segment (
  email_body_segment_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_attachment (
  email_attachment_id text PRIMARY KEY,
  attachment_fingerprint text NOT NULL,
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS email_attachment_occurrence (
  email_attachment_occurrence_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  email_attachment_id text NOT NULL REFERENCES email_attachment(email_attachment_id),
  email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quoted_message_candidate (
  quoted_message_candidate_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS embedded_message_relation (
  embedded_message_relation_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  parent_email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  embedded_email_message_id text NOT NULL REFERENCES email_message(email_message_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mail_parse_run (
  mail_parse_run_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mail_parse_warning (
  mail_parse_warning_id text PRIMARY KEY,
  mail_import_session_id text NOT NULL REFERENCES mail_import_session(mail_import_session_id),
  mail_parse_run_id text NOT NULL REFERENCES mail_parse_run(mail_parse_run_id),
  workspace_id text NOT NULL,
  owner_user_id text NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mail_import_session_workspace_owner
  ON mail_import_session (workspace_id, owner_user_id);
CREATE INDEX IF NOT EXISTS idx_mail_import_session_upload_session
  ON mail_import_session (upload_session_id);
CREATE INDEX IF NOT EXISTS idx_mail_archive_occurrence_import
  ON mail_archive_occurrence (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_mail_folder_occurrence_import
  ON mail_folder_occurrence (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_email_message_fingerprint
  ON email_message (message_fingerprint);
CREATE INDEX IF NOT EXISTS idx_email_message_occurrence_import
  ON email_message_occurrence (mail_import_session_id, email_message_id);
CREATE INDEX IF NOT EXISTS idx_email_body_segment_import_message
  ON email_body_segment (mail_import_session_id, email_message_id);
CREATE INDEX IF NOT EXISTS idx_email_attachment_fingerprint
  ON email_attachment (attachment_fingerprint);
CREATE INDEX IF NOT EXISTS idx_email_attachment_occurrence_import
  ON email_attachment_occurrence (mail_import_session_id, email_attachment_id);
CREATE INDEX IF NOT EXISTS idx_quoted_message_candidate_import
  ON quoted_message_candidate (mail_import_session_id, email_message_id);
CREATE INDEX IF NOT EXISTS idx_embedded_message_relation_import
  ON embedded_message_relation (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_mail_parse_run_import
  ON mail_parse_run (mail_import_session_id);
CREATE INDEX IF NOT EXISTS idx_mail_parse_warning_import
  ON mail_parse_warning (mail_import_session_id, mail_parse_run_id);
