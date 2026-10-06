-- Google-backed FormOwl OAuth identity and authorization-session records.
--
-- Google credentials and tokens never enter these tables.  Only stable
-- identity attributes, one-way hashes, authenticated ciphertext for the
-- downstream OAuth client's state, and FormOwl authorization state persist.

CREATE TABLE IF NOT EXISTS formowl_users (
    user_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    email TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS formowl_workspace_members (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL,
    removed_at TIMESTAMPTZ,
    PRIMARY KEY (workspace_id, user_id)
);

CREATE TABLE IF NOT EXISTS formowl_external_identities (
    external_identity_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL CHECK (provider = 'google'),
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    email TEXT NOT NULL,
    email_verified BOOLEAN NOT NULL CHECK (email_verified),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_at TIMESTAMPTZ NOT NULL,
    last_authenticated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (issuer, subject),
    CONSTRAINT uq_formowl_external_identity_user
        UNIQUE (external_identity_id, user_id)
);

DO $formowl_migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_formowl_external_identity_user'
          AND conrelid = 'formowl_external_identities'::regclass
    ) THEN
        ALTER TABLE formowl_external_identities
            ADD CONSTRAINT uq_formowl_external_identity_user
            UNIQUE (external_identity_id, user_id);
    END IF;
END
$formowl_migration$;

CREATE TABLE IF NOT EXISTS formowl_oauth_invitations (
    invitation_id TEXT PRIMARY KEY,
    normalized_email TEXT NOT NULL,
    intended_user_id TEXT REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    workspace_id TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'revoked', 'expired')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    accepted_external_identity_id TEXT REFERENCES formowl_external_identities(external_identity_id)
        ON DELETE RESTRICT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_formowl_oauth_invitation_active_email
    ON formowl_oauth_invitations (normalized_email)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS formowl_oauth_owner_bootstraps (
    workspace_id TEXT PRIMARY KEY,
    idempotency_key_hash TEXT NOT NULL,
    normalized_email TEXT NOT NULL,
    invitation_id TEXT NOT NULL UNIQUE,
    operator_service_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'completed')),
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    CHECK (
        (status = 'pending' AND completed_at IS NULL)
        OR (status = 'completed' AND completed_at IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_formowl_oauth_owner_bootstraps_status
    ON formowl_oauth_owner_bootstraps (status, created_at);

CREATE TABLE IF NOT EXISTS formowl_oauth_client_authorizations (
    oauth_client_authorization_id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL,
    external_identity_id TEXT NOT NULL
        REFERENCES formowl_external_identities(external_identity_id) ON DELETE RESTRICT,
    user_id TEXT NOT NULL REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    granted_scopes TEXT[] NOT NULL,
    default_workspace_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    UNIQUE (client_id, external_identity_id),
    CONSTRAINT fk_formowl_client_authorization_identity_user
        FOREIGN KEY (external_identity_id, user_id)
        REFERENCES formowl_external_identities(external_identity_id, user_id)
        ON DELETE RESTRICT
);

DO $formowl_migration$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_formowl_client_authorization_identity_user'
          AND conrelid = 'formowl_oauth_client_authorizations'::regclass
    ) THEN
        ALTER TABLE formowl_oauth_client_authorizations
            ADD CONSTRAINT fk_formowl_client_authorization_identity_user
            FOREIGN KEY (external_identity_id, user_id)
            REFERENCES formowl_external_identities(external_identity_id, user_id)
            ON DELETE RESTRICT;
    END IF;
END
$formowl_migration$;

CREATE TABLE IF NOT EXISTS formowl_oauth_transactions (
    transaction_id TEXT PRIMARY KEY,
    google_state_hash TEXT NOT NULL UNIQUE,
    encrypted_client_state TEXT NOT NULL,
    google_nonce_hash TEXT NOT NULL,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    resource TEXT NOT NULL,
    scopes TEXT[] NOT NULL,
    code_challenge TEXT NOT NULL,
    code_challenge_method TEXT NOT NULL CHECK (code_challenge_method = 'S256'),
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'consumed', 'failed')),
    consumed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_formowl_oauth_transactions_effective
    ON formowl_oauth_transactions (google_state_hash, status, expires_at);

CREATE TABLE IF NOT EXISTS formowl_oauth_authorization_codes (
    code_hash TEXT PRIMARY KEY,
    transaction_id TEXT NOT NULL UNIQUE
        REFERENCES formowl_oauth_transactions(transaction_id) ON DELETE RESTRICT,
    user_id TEXT NOT NULL REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    external_identity_id TEXT NOT NULL
        REFERENCES formowl_external_identities(external_identity_id) ON DELETE RESTRICT,
    client_id TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    resource TEXT NOT NULL,
    scopes TEXT[] NOT NULL,
    code_challenge TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_formowl_oauth_codes_effective
    ON formowl_oauth_authorization_codes (code_hash, expires_at, consumed_at);

CREATE TABLE IF NOT EXISTS formowl_oauth_token_sessions (
    token_session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES formowl_users(user_id) ON DELETE RESTRICT,
    external_identity_id TEXT NOT NULL
        REFERENCES formowl_external_identities(external_identity_id) ON DELETE RESTRICT,
    oauth_client_authorization_id TEXT NOT NULL
        REFERENCES formowl_oauth_client_authorizations(oauth_client_authorization_id)
        ON DELETE RESTRICT,
    client_id TEXT NOT NULL,
    current_workspace_id TEXT NOT NULL,
    resource TEXT NOT NULL,
    scopes TEXT[] NOT NULL,
    token_jti_hash TEXT NOT NULL UNIQUE,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revocation_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_formowl_oauth_token_sessions_effective
    ON formowl_oauth_token_sessions (token_session_id, user_id, expires_at, revoked_at);

ALTER TABLE formowl_audit_log
    ALTER COLUMN actor_user_id DROP NOT NULL;

ALTER TABLE formowl_audit_log
    ADD COLUMN IF NOT EXISTS actor_type TEXT NOT NULL DEFAULT 'user',
    ADD COLUMN IF NOT EXISTS actor_service_id TEXT,
    ADD COLUMN IF NOT EXISTS external_identity_id TEXT,
    ADD COLUMN IF NOT EXISTS oauth_client_id TEXT,
    ADD COLUMN IF NOT EXISTS oauth_token_session_id TEXT,
    ADD COLUMN IF NOT EXISTS request_id TEXT,
    ADD COLUMN IF NOT EXISTS tool_call_id TEXT,
    ADD COLUMN IF NOT EXISTS reason_code TEXT;

ALTER TABLE formowl_audit_log
    DROP CONSTRAINT IF EXISTS chk_formowl_audit_actor_identity;

ALTER TABLE formowl_audit_log
    ADD CONSTRAINT chk_formowl_audit_actor_identity CHECK (
        (
            actor_type = 'user'
            AND actor_user_id IS NOT NULL
            AND actor_service_id IS NULL
        )
        OR (
            actor_type = 'service'
            AND actor_user_id IS NULL
            AND actor_service_id IS NOT NULL
        )
        OR (
            actor_type = 'external_unauthenticated'
            AND actor_user_id IS NULL
            AND actor_service_id IS NULL
        )
    );

CREATE INDEX IF NOT EXISTS idx_formowl_audit_log_oauth_lineage
    ON formowl_audit_log (
        external_identity_id,
        oauth_client_id,
        oauth_token_session_id,
        request_id,
        tool_call_id,
        timestamp
    );

CREATE INDEX IF NOT EXISTS idx_formowl_audit_log_actor_service
    ON formowl_audit_log (actor_service_id, timestamp)
    WHERE actor_service_id IS NOT NULL;
