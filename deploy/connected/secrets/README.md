# Connected runtime secrets

This directory is a gitignored, operator-controlled mount point. Only this
README belongs in Git. Every generated secret file remains ignored operator
state. Secret values must never be committed, pasted into ChatGPT, put on a
command line, or copied into logs and evidence reports.

## Generate the FormOwl and PostgreSQL secrets

Build the runtime image, capture its immutable image ID, then run the
initializer as the host user so the bind-mounted files remain operator-owned:

```sh
mkdir -p .test-tmp
docker build -f containers/runtime/Dockerfile \
  --iidfile .test-tmp/issue20-runtime-image.iid \
  .
FORMOWL_RUNTIME_IMAGE="$(tr -d '\r\n' \
  < .test-tmp/issue20-runtime-image.iid)"
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  "$FORMOWL_RUNTIME_IMAGE" init-secrets --output-dir /secrets
```

Require `FORMOWL_RUNTIME_IMAGE` to match
`sha256:<64 lowercase hex>` before using it. Use this exact built-image command
for a deployment with no generated secret entries. This is the immutable-image
equivalent of the older tagged command tail
`formowl-runtime:local init-secrets --output-dir /secrets`; do not replace the
captured image ID with that mutable tag. Do not invoke
`init-secrets` through either the `connected-mcp` or `connected-migrate`
Compose service: both services require the very secret files that this command
creates, so Compose rejects a clean target before the CLI can start. The
tracked `README.md` may already exist in this directory. Before first
initialization, there must be no generated target, initializer lock or staging
entry, recovery/quarantine directory, or `google-client-secret`. The directory
must be operator-owned and writable only by the approved operator; the
initializer itself does not require host Python or any pre-existing FormOwl
secret.

The command creates exactly these six generated files with mode `0400`; the
directory is mode `0700`:

```text
postgres-password
database-dsn
state-encryption-key
signing-key-set.json
signing-current.pem
signing-previous.pem
```

The password embedded in `database-dsn` is the same generated value used by
`postgres-password`. `state-encryption-key` is a Fernet key. The signing files
are distinct RSA private keys.

The initial `signing-key-set.json` contains only `signing-current.pem` as the
single active key. `signing-previous.pem` is an unused standby mount slot needed
by the current Compose layout; it is not listed in the initial manifest, is not
published through JWKS, and must not be treated as an already-active previous
key. During rotation the two mount slots may exchange active/previous roles;
the manifest, `active` flag, key id, and `verify_until` are authoritative, not
the filenames. `../signing-key-set.example.json` shows the initial one-key
manifest shape.

An identical rerun validates the complete set and returns `unchanged`. It never
overwrites an existing secret. Output contains only status, counts, and a hash
of the non-secret initialization contract.

## Inject the Google client secret separately

The initializer deliberately does not create `google-client-secret`. Google is
the external credential issuer, so an empty or fabricated placeholder is
invalid. Create a Google OAuth client of type **Web application**, register the
exact `https://<public-host>/oauth/google/callback` redirect, and download its
client JSON to an operator-controlled location. Do not copy the JSON into this
directory and do not extract the secret by hand. The repository helper verifies
the expected client ID and redirect URI, writes only the raw secret, uses
exclusive mode-`0400` creation, and never prints the secret:

```sh
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --network none \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  -v "/operator-controlled/google-oauth-client.json:/input/google-client.json:ro" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  import-google-client-secret \
  --credential-json /input/google-client.json \
  --output /secrets/google-client-secret \
  --expected-client-id "$FORMOWL_GOOGLE_CLIENT_ID" \
  --expected-redirect-uri "$FORMOWL_GOOGLE_REDIRECT_URI"
```

Do not use a shell command that places the client-secret value in argv,
environment variables, terminal output, or shell history. The helper rejects
an installed-app client, malformed/download-mismatched JSON, a client-ID or
redirect mismatch, and an existing output instead of overwriting it.

The initializer reports:

```text
google_client_secret_generated=false
requires_operator_google_client_secret=true
supports_connected_preflight_ready=false
```

Therefore initializer `status=ok` means only that the six generated files are
complete. It does not mean Google configuration, PostgreSQL migration,
connected runtime preflight, TLS, or ChatGPT connectivity is ready.

## Recover an interrupted first initialization

If initialization reports `secret_recovery_required`, do not guess which files
to delete and do not hand-edit a partial set. Before any `migrate`, `preflight`,
or `serve` command has consumed the set, ensure the connected stack is stopped
and run the explicit whole-entry recovery:

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  "$FORMOWL_RUNTIME_IMAGE" init-secrets --output-dir /secrets --recover-partial
```

The helper moves every generated partial target and stale initializer staging
entry into one new hidden mode-`0700` recovery directory, then creates and
validates a fresh complete set. It does not move or create
`google-client-secret`. The public result reports only recovered counts, never
the recovery path or recovered values.

If any partial value was already used by PostgreSQL or a connected service, or
if a complete set fails validation, stop instead of using recovery. Treat that
as a credential-rotation incident. Keep the quarantined directory until the
fresh set passes migration and preflight and the operator's retention policy
allows secure disposal.
