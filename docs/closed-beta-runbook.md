# Closed Beta Runbook

This is the operator runbook for the connected FormOwl closed-beta path:

```text
public HTTPS /mcp
  -> FormOwl OAuth 2.1 with exact resource/callback binding and PKCE S256
  -> Google OIDC
  -> FormOwl (issuer, subject) identity mapping
  -> resource-bound FormOwl token session
  -> fresh gateway-controlled ActorContext
  -> whoami and governed MCP tools
```

The repository implements the components for this path, but the live journeys
in this runbook are still external completion gates. Do not mark issue #20
complete or claim production readiness merely because repository or offline
tests pass.

Current external-evidence state remains incomplete. All seven required packet
layers are explicitly `not_supplied`:

```text
live_postgresql = not_supplied
operator_cli_postgresql = not_supplied
production_container_lifecycle = not_supplied
mcp_inspector = not_supplied
live_chatgpt_google = not_supplied
reviewer_gate = not_supplied
completion_audit = not_supplied
```

Current verified local authority is 689/689/689
changed/manifested/onboarded with pending 0; the whole harness is
508/508/508/508 requested/resolved/run/pass across 1,388 checked evidence
pairs. Direct trace is expected/covered 689/689 with missing 0 and blockers
`[]`; `test_id_count` is 1,521. The canonical full suite reported
`Ran 1521 tests in 964.613s` and `OK (skipped=7)`. Ruff check passed, Ruff
format reported 306 files already formatted, and runner shell syntax, JSON
parse, and `git diff --check` passed.

The latest local harness artifact is
`/tmp/formowl-issue20-postfix-local-harness-20260721T100124Z.json`, SHA-256
`1adaeaf752148e730f421e0e385b0faa4a1aef4273d437def902bdb212e352b1`.
It still supports neither closure nor production readiness. Connector-confirmed
GitHub current main remains
`342e588aa6162ccbdd14a257bfc09e58e7a619ad`, with no newer remote main
reported; this does not satisfy an external evidence layer.

The current OpenAI operator references are:

- Authentication: <https://developers.openai.com/apps-sdk/build/auth>
- Connect from ChatGPT: <https://developers.openai.com/apps-sdk/deploy/connect-chatgpt>
- Test the integration: <https://developers.openai.com/apps-sdk/deploy/testing>

Use those pages as the authority if the ChatGPT UI labels move. The steps below
record the stricter FormOwl closed-beta evidence boundary on top of the general
OpenAI guidance.

The official Apps SDK authentication guidance explicitly accounts for
predefined OAuth clients and token-endpoint authentication methods. It does not
prove that this workspace's current ChatGPT Apps management UI exposes entry or
selection for FormOwl's exact predefined client ID. Use the operator-recorded
ID if the live UI supports it; otherwise stop before live login and record the
interoperability blocker. Do not claim predefined clients are unsupported, and
do not claim UI support without live evidence.

### Canonical clean-clone execution order

Do not reorder or combine these gates:

1. **Create ignored operator state.** Copy the tracked non-secret env and
   Caddy templates to `.formowl/issue20/`.
2. **Build and export immutable image IDs.** Capture the runtime IID, resolve
   the Caddy image ID, and keep the pinned PostgreSQL digest.
3. **Select and record the predefined client ID.** Use the containerized
   helper to derive or validate one stable non-secret safe value before
   discovery.
4. **Initialize the six generated secrets.** The tracked secrets `README.md`
   may already exist; generated targets, staging/lock entries, and
   recovery/quarantine entries must not.
5. **Install the Google client secret separately.** Import the downloaded
   Google Web application JSON without printing or shell-exporting its secret.
6. **Write discovery configuration.** Keep the recorded real predefined
   client ID and use only the exact reserved redirect sentinel.
7. **Start discovery with no dependencies.** Start the loopback backend and
   the Compose `public-tls` host-network service.
8. **Create or refresh the ChatGPT developer-mode app.** Give app management
   the now-reachable public HTTPS `/mcp` URL and configure it to use the same
   predefined client ID if the UI supports that choice. If it does not, stop
   and record an external live blocker.
9. **Copy the exact ChatGPT callback.** App management supplies the production
   callback; it does not supply or generate the recorded client ID.
10. **Stop and remove discovery.** Stop the Compose TLS service and remove the
   named no-dependency backend before changing configuration.
11. **Finalize the ignored operator env.** Replace only the redirect sentinel
    with the exact callback and render Compose while discovery is stopped.
12. **Start PostgreSQL.**
13. **Run migrations.**
14. **Require ready preflight.**
15. **Bootstrap the first owner.**
16. **Serve, refresh the app, and start a new conversation.**
17. **Complete the owner and second-user journeys.**
18. **Complete the operator CLI lifecycle.**
19. **Run the official MCP Inspector package with `npx`.**
20. **Complete live denial and fresh-relink journeys.** Cover revocation,
    membership removal/restore, fixed-lifetime expiry, and fresh OAuth relink.
21. **Prepare the Issue-wide reviewer packet.**
22. **Run the independent completion audit.**

## 1. Public Origin and Provider Prerequisites

Choose one canonical public HTTPS origin with no trailing slash. Configure all
of these as exact values:

```text
FORMOWL_AUTH_MODE=oauth_google
FORMOWL_OAUTH_ISSUER=https://<public-host>
FORMOWL_MCP_RESOURCE=https://<public-host>/mcp
FORMOWL_CHATGPT_CLIENT_ID=<predefined-client-id>
FORMOWL_GOOGLE_REDIRECT_URI=https://<public-host>/oauth/google/callback
FORMOWL_GOOGLE_CLIENT_ID=<google-client-id>
FORMOWL_CHATGPT_REDIRECT_URI=https://chatgpt.com/connector/oauth/<callback-id>
FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID=<authorized-operator-service-id>
```

Run every command from the repository root in a Bash-compatible shell on a
Linux Docker host. The clean-clone host prerequisites are Docker Engine with
BuildKit, Docker Compose v2 (`docker compose`), outbound DNS/HTTPS access, and
standard POSIX/coreutils commands used below (`grep`, `id`, `mkdir`, `stat`,
and `tr`). No host Python, Caddy, PostgreSQL client, OpenSSL CLI, `curl`, `jq`,
systemd, or root-owned configuration file is required. Node.js with `npx` is
required only for the official MCP Inspector journey in section 11.

The predefined ChatGPT client ID is a stable non-secret value selected and
recorded by the FormOwl deployment operator before discovery. ChatGPT Apps
management supplies and shows only the production callback after its
developer-mode app can reach the public HTTPS MCP server. This remains a
one-predefined-client architecture: ChatGPT is the client, and this runbook
makes no dynamic-client registration claim. Copy the tracked
`deploy/connected/compose.env.example` to operator-controlled state at
`.formowl/issue20/compose.env`. It is a non-secret worksheet; the validated
final environment and Caddy configuration remain ignored and
operator-controlled.

Operator-local `deploy/connected/compose.env` and
`deploy/connected/Caddyfile` are also exact Git and Docker build-snapshot
exclusions. They are never authoritative template or image inputs. The tracked
`compose.env.example`, `Caddyfile.example`, and other tracked templates remain
included and are the only files operators copy from.

The OAuth issuer must be an origin, the MCP resource must equal
`{issuer}/mcp`, and the Google callback must equal
`{issuer}/oauth/google/callback`. A production ChatGPT callback is accepted
only as `https://chatgpt.com/connector/oauth/{callback_id}`, where
`callback_id` is one non-empty RFC-unreserved path segment. The origin is fixed
and lowercase; userinfo, ports, percent encoding, extra path segments, query,
fragment, and wildcards are rejected. The only non-production exception is the
exact redirect sentinel in section 1.1. The legacy
`formowl-discovery-only` client-ID sentinel and tracked worksheet placeholders
are rejected. HTTP remains limited to explicit loopback-only tests.

Before starting FormOwl, the deployment operator must complete these external
prerequisites:

- Create/choose one public DNS hostname. Its A record must point to this host;
  if an AAAA record exists, IPv6 must also reach this host. Do not continue
  while DNS still points elsewhere.
- Permit inbound TCP 80 and 443 to the Docker host and outbound DNS plus HTTPS.
  UDP 443 is optional HTTP/3. Ports 80 and 443 must not already be owned by
  another process or container.
- Supply a durable operator email for ACME notices. The Compose `public-tls`
  service uses host networking, an operator-owned copy of
  `deploy/connected/Caddyfile.example`, and persistent Caddy data/config
  volumes to obtain and renew a public certificate.
- In Google Cloud, configure the OAuth consent screen as an internal app for an
  eligible Workspace or as an external app in **Testing**. When Testing is
  used, add both real closed-beta Google accounts as test users.
- Create a Google OAuth client of type **Web application**, register exactly
  `https://<public-host>/oauth/google/callback`, and use the OIDC scopes
  `openid email profile`. Download the client JSON for the safe import in
  section 2.
- Select and record one stable safe predefined client ID before discovery.
  Section 2 provides a deterministic containerized helper and does not require
  host Python.
- Create or refresh the ChatGPT developer-mode app only after the public
  `https://<public-host>/mcp` resource is reachable. Configure app management
  to use the same operator-chosen predefined client ID if the current UI
  supports that choice. If the UI does not expose a way to configure or select
  that predefined client ID, stop and record an external live blocker; do not
  invent an ID or claim ChatGPT generated or displayed one. Copy only the exact
  production callback shown by app management.

The public TLS service uses host networking only so Caddy can proxy to the
Compose-published `127.0.0.1:8000` backend. It preserves paths and the public
host/proto headers. PostgreSQL has no host port. Do not expose object storage,
worker/control-plane endpoints, or the loopback backend directly to ChatGPT.

The public same-origin routes are:

```text
/.well-known/oauth-protected-resource
/.well-known/oauth-authorization-server
/.well-known/jwks.json
/oauth/authorize
/oauth/google/callback
/oauth/token
/mcp
/healthz
/readyz
```

### 1.1 Obtain the exact ChatGPT callback without creating identity state

The official ChatGPT developer-mode flow needs the public HTTPS MCP server to
be reachable before the app can be created or refreshed. Clean-clone discovery
therefore keeps the already recorded real predefined client ID and uses only
the exact reserved redirect sentinel:

```text
FORMOWL_CHATGPT_CLIENT_ID=<operator-chosen-safe-predefined-client-id>
FORMOWL_CHATGPT_REDIRECT_URI=https://invalid.example.invalid/formowl-discovery-only
```

The redirect sentinel alone selects discovery mode. The same real client ID is
required in discovery and final mode; the legacy client-ID sentinel, worksheet
placeholder, unsafe ID, or any attempt to change the ID during finalization
fails closed. Section 3 gives the exact public start/check/stop/replacement
sequence before PostgreSQL, migration, normal preflight, or bootstrap. Use
ChatGPT app management only to create or refresh the developer-mode app against
the reachable public `/mcp` resource. Configure it to use the same predefined
client ID if that UI supports the choice; otherwise stop and record the missing
choice as an external live blocker. App management supplies only the displayed
`https://chatgpt.com/connector/oauth/{callback_id}`. Do not substitute another
OpenAI URL, a tunnel, or any reachable third-party callback, and never claim
ChatGPT generated or displayed the client ID.

The sentinel configuration may run only public MCP `initialize`, `tools/list`,
and protected-tool OAuth challenges. It must keep `/readyz` at HTTP 503 with
`status: discovery_only`. FormOwl blocks bootstrap, invitations, operator
lookup/mutation, OAuth transactions, Google callback completion, code exchange,
membership changes, token revocation, and related audit writers before state
changes. It also ignores bearer credentials instead of validating old tokens.
Any newly created identity, invitation, authorization, code, token session,
membership, revocation, or discovery-denial audit is a failed invariant.

The sentinel phase proves only public discovery. It is never OAuth, callback,
Google-login, authenticated-tool, or issue-completion evidence.

## 2. Immutable Images, Secrets, and Compose Configuration

Create ignored operator state before building or running
containers. The copied env file contains no secret values. The copied Caddyfile
contains no production hostname and is parameterized by the operator shell:

```sh
FORMOWL_OPERATOR_DIR="$PWD/.formowl/issue20"
FORMOWL_COMPOSE_ENV="$FORMOWL_OPERATOR_DIR/compose.env"
FORMOWL_CADDYFILE="$FORMOWL_OPERATOR_DIR/Caddyfile"
COMPOSE_ENV="$FORMOWL_COMPOSE_ENV"
install -d -m 0700 "$FORMOWL_OPERATOR_DIR"
install -m 0600 deploy/connected/compose.env.example "$FORMOWL_COMPOSE_ENV"
install -m 0600 deploy/connected/Caddyfile.example "$FORMOWL_CADDYFILE"
export FORMOWL_OPERATOR_DIR FORMOWL_COMPOSE_ENV FORMOWL_CADDYFILE COMPOSE_ENV
```

The actual operator environment stays at the ignored
`.formowl/issue20/compose.env`. Its values are non-secret configuration and
secret-file paths, not shell secrets. The secret file contents remain in
operator-owned mode-`0400` files and are never copied into the env file.

Build the runtime once, capture Docker's immutable image ID, pull the official
Caddy image once and resolve its immutable local image ID, and pin PostgreSQL
to the repository-approved digest. Mutable tags are acquisition conveniences
only; Compose receives only the resolved runtime/Caddy IDs and PostgreSQL
digest.

```sh
mkdir -p .test-tmp
RUNTIME_IID_FILE=.test-tmp/issue20-runtime-image.iid
docker build \
  --file containers/runtime/Dockerfile \
  --iidfile "$RUNTIME_IID_FILE" \
  .
FORMOWL_RUNTIME_IMAGE="$(tr -d '\r\n' < "$RUNTIME_IID_FILE")"
if [[ ! "$FORMOWL_RUNTIME_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "invalid immutable runtime image id" >&2
  exit 1
fi
export FORMOWL_RUNTIME_IMAGE
export FORMOWL_POSTGRES_IMAGE='pgvector/pgvector@sha256:131dcf7ff6a900545df8e7e092c270aa8c6db2f2c818e408cb45ec21316b74e6'
docker pull caddy:2-alpine
FORMOWL_TLS_PROXY_IMAGE="$(
  docker image inspect --format '{{.Id}}' caddy:2-alpine
)"
if [[ ! "$FORMOWL_TLS_PROXY_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "invalid immutable Caddy image id" >&2
  exit 1
fi
export FORMOWL_TLS_PROXY_IMAGE
```

Every final `docker run`, Compose `preflight`, migration, service, and evidence
command must use those resolved values. A missing IID, short digest, tag, or
different PostgreSQL reference is a stop condition.

Choose a campaign-unique Compose project name that has never been used on this
host. Derive and record the stable non-secret predefined client ID before
discovery. This uses only the built runtime image and the ignored operator
directory; it does not require host Python and does not print or expose any
secret:

```sh
FORMOWL_PROJECT_NAME='formowl-issue20-unique-campaign-name'
FORMOWL_CHATGPT_CLIENT_ID_FILE="$FORMOWL_OPERATOR_DIR/chatgpt-predefined-client-id"
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --network none \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  -v "$FORMOWL_OPERATOR_DIR:/operator" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  predefined-client-id \
  --deployment-id "$FORMOWL_PROJECT_NAME" \
  --output /operator/chatgpt-predefined-client-id
FORMOWL_CHATGPT_CLIENT_ID="$(
  tr -d '\r\n' < "$FORMOWL_CHATGPT_CLIENT_ID_FILE"
)"
export FORMOWL_PROJECT_NAME FORMOWL_CHATGPT_CLIENT_ID_FILE
export FORMOWL_CHATGPT_CLIENT_ID
```

The helper derives `formowl-chatgpt-<deployment-id>`, validates the same safe
identifier grammar enforced by the OAuth bridge, writes the non-secret value
as a mode-`0600` operator file, and refuses to overwrite an existing record.
An operator with an independently assigned predefined client ID may validate
it with `predefined-client-id --client-id <value>` instead. The legacy
`formowl-discovery-only` client ID, tracked worksheet placeholders, slashes,
whitespace, control characters, and overlong values are rejected.

Initialize the generated secret set from the clean clone. The tracked
`deploy/connected/secrets/README.md` is expected to exist; the required clean
state is the absence of generated targets, initializer lock/staging entries,
recovery/quarantine entries, and `google-client-secret`. Run the container as
the host user so the bind-mounted files remain operator-owned:

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  "$FORMOWL_RUNTIME_IMAGE" init-secrets --output-dir /secrets
```

This exact built-image `docker run` path is the bootstrap command. Do not invoke
`init-secrets` through either the `connected-mcp` or `connected-migrate`
Compose service: those services declare the generated files as required
Compose secrets, so a deployment with no generated targets cannot resolve the
service far enough to start the initializer. The directory must be
operator-owned; no host Python package or pre-existing FormOwl secret is
required by the command above.

The helper creates the directory with mode `0700` and these six generated files
with mode `0400`:

```text
postgres-password
database-dsn
state-encryption-key
signing-key-set.json
signing-current.pem
signing-previous.pem
```

The initial manifest contains exactly one active key referencing
`signing-current.pem`. The separately generated `signing-previous.pem` is an
unused standby mount slot required by the current Compose layout. It is absent
from the initial manifest and JWKS. The slot filename does not permanently
define its role: during rotation, the manifest's key id, `active` flag, and
`verify_until` determine which mounted key is current or previous.

The helper never overwrites existing secrets. A complete valid rerun returns
`secret_set_state: unchanged`. Its output contains only status, counts, and a
hash of the non-secret initialization contract.

The Google OAuth client secret is not generated by FormOwl. Set the following
non-secret shell values from the approved provider/operator records, then
import the downloaded Google **Web application** JSON. The downloaded JSON is
mounted read-only; the helper verifies the client ID and exact callback,
creates only the raw `google-client-secret` with mode `0400`, never overwrites
it, and never prints it:

```sh
FORMOWL_PUBLIC_HOST='<public-host>'
FORMOWL_ACME_EMAIL='operator@example.com'
FORMOWL_GOOGLE_CLIENT_ID='<google-web-client-id>'
FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID='<authorized-operator-service-id>'
FORMOWL_GOOGLE_REDIRECT_URI="https://$FORMOWL_PUBLIC_HOST/oauth/google/callback"
export FORMOWL_PUBLIC_HOST FORMOWL_ACME_EMAIL
export FORMOWL_GOOGLE_CLIENT_ID FORMOWL_GOOGLE_REDIRECT_URI
export FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID

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

Do not extract the client secret by hand, put its value in argv/environment/
history, or create an empty placeholder. The initializer deliberately reports
`google_client_secret_generated=false`,
`requires_operator_google_client_secret=true`, and
`supports_connected_preflight_ready=false`. Its `status: ok` means only that
the six generated files are complete; it is not migration, provider, runtime,
TLS, or ChatGPT readiness evidence.

Keep the stable project and predefined client ID selected above. The
clean-clone discovery configuration changes only the redirect to the exact
sentinel:

```sh
FORMOWL_CHATGPT_REDIRECT_URI='https://invalid.example.invalid/formowl-discovery-only'
export FORMOWL_CHATGPT_REDIRECT_URI

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --network none \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  -v "$FORMOWL_OPERATOR_DIR:/operator" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  write-compose-env \
  --replace \
  --output /operator/compose.env \
  --project-name "$FORMOWL_PROJECT_NAME" \
  --runtime-image "$FORMOWL_RUNTIME_IMAGE" \
  --tls-proxy-image "$FORMOWL_TLS_PROXY_IMAGE" \
  --public-host "$FORMOWL_PUBLIC_HOST" \
  --acme-email "$FORMOWL_ACME_EMAIL" \
  --chatgpt-client-id "$FORMOWL_CHATGPT_CLIENT_ID" \
  --chatgpt-redirect-uri "$FORMOWL_CHATGPT_REDIRECT_URI" \
  --google-client-id "$FORMOWL_GOOGLE_CLIENT_ID" \
  --owner-bootstrap-operator-service-id \
    "$FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID"
printf '%s\n' 'FORMOWL_CADDYFILE=./.formowl/issue20/Caddyfile' \
  >> "$FORMOWL_COMPOSE_ENV"
```

The helper derives the issuer, MCP resource, and Google callback instead of
accepting three independently editable values. It preserves mode `0600`,
requires the copied target to be a single regular operator-owned file, and
contains no secret values. The following `printf` restores the explicit
operator-controlled Caddyfile path after each `--replace`; it appends no secret
value. Every Compose command below uses the
`COMPOSE_ENV="$FORMOWL_COMPOSE_ENV"` alias with `--env-file "$COMPOSE_ENV"`;
never use the tracked template directly.

Before starting PostgreSQL, require that this project name has no existing
Compose volumes. Reusing a named volume is not fresh-database evidence; stop
and choose another never-used project name rather than deleting or resetting a
possibly owned volume:

```sh
if docker volume ls --quiet \
  --filter "label=com.docker.compose.project=$FORMOWL_PROJECT_NAME" |
  grep -q .; then
  echo "Compose project name already owns volumes; choose a new name" >&2
  exit 1
fi

docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  config --format json > .test-tmp/issue20-compose-config.json
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" config --images
```

Require the rendered connected services to use the runtime IID, PostgreSQL to
use the pinned digest, and `public-tls` to use the Caddy IID. The backend port
must render as `127.0.0.1:8000`; PostgreSQL must have no published port.
`public-tls` must render with `network_mode: host`, no `ports`, and exactly the
ignored operator Caddyfile mounted read-only at `/etc/caddy/Caddyfile`.

If the helper reports `secret_recovery_required`, do not guess which partial
files to delete. Before any generated value has been used by `migrate`,
`preflight`, PostgreSQL, or `serve`, stop the connected stack and run:

```sh
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/deploy/connected/secrets:/secrets" \
  "$FORMOWL_RUNTIME_IMAGE" init-secrets --output-dir /secrets --recover-partial
```

This moves every generated partial target and stale staging entry into one new
hidden mode-`0700` quarantine directory and creates a fresh complete set. It
does not move or create `google-client-secret`, and reports only recovered
counts. If a partial value was already consumed or a complete set is invalid,
stop and treat it as credential rotation instead of using recovery. Keep the
quarantine until the fresh deployment passes preflight and the retention policy
allows secure disposal. The precise recovery contract is also documented in
`deploy/connected/secrets/README.md`.

`database-dsn`, the PostgreSQL password, Google client secret, OAuth
state-encryption key, and all signing private keys are secrets. Pass only file
paths through `*_FILE` configuration. Never place values in command arguments,
tracked files, ordinary environment variables, screenshots, logs, evidence
packets, or ChatGPT messages.

`deploy/connected/signing-key-set.example.json` shows the initial one-key shape.
Every inactive verification key added during rotation must have an RFC 3339
`verify_until`; an active key must not. Each key id and private-key file must be
unique.

The connected runtime must use `FORMOWL_AUTH_MODE=oauth_google`. Remove
`FORMOWL_MCP_SESSION_ID`, `FORMOWL_MCP_ACTOR_USER_ID`, and
`FORMOWL_MCP_WORKSPACE_ID`; their presence makes connected startup fail. The
plaintext secret variables `FORMOWL_DATABASE_DSN`,
`FORMOWL_GOOGLE_CLIENT_SECRET`, `FORMOWL_OAUTH_STATE_ENCRYPTION_KEY`, and
signing-key equivalents are also rejected.

The local operator commands in this runbook are not MCP tools and are not
reachable through public `/mcp`. `FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID`
is an audit attribution identifier, not a password. Knowing it does not grant
remote authority. The actual authorization boundary is controlled access to
the deployment shell, Docker daemon, Compose configuration, database secret,
and mounted files. Keep those controls restricted to approved operators.

## 3. Fresh PostgreSQL, Migration, and Preflight

Use a newly provisioned empty PostgreSQL database for the completion journey.
Do not reuse fixture state as fresh-database evidence. Every Compose command in
this runbook includes the same ignored environment file; do not omit it or fall
back to the Compose defaults.

Discovery must finish before PostgreSQL, migration, normal preflight, or
bootstrap. The recorded real predefined client ID must remain active while the
exact redirect sentinel selects discovery.

Start one no-dependency FormOwl discovery container with the app port published
only on loopback. Start the same Compose `public-tls` service used by the final
deployment with `--no-deps`; its host-network Caddy reads the ignored
operator-controlled Caddyfile and proxies to that loopback port:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --detach --name formowl-discovery-only \
  --no-deps --service-ports connected-mcp serve
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  --profile public-tls up -d --no-deps public-tls
docker inspect --format '{{.State.Running}}' formowl-discovery-only
docker run --rm \
  --read-only \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  check-public \
  --origin "https://$FORMOWL_PUBLIC_HOST" \
  --mode discovery
```

Require the inspect result to be `true`, `/healthz` to be HTTP 200, and
`/readyz` to be HTTP 503 with `status: discovery_only`. Use ChatGPT app
management to create or refresh the developer-mode app against
`https://<public-host>/mcp`. If app management supports predefined-client
selection or entry, configure the exact value already recorded in
`FORMOWL_CHATGPT_CLIENT_ID`. If it does not, stop, leave Issue #20 open, and
record `chatgpt_predefined_client_configuration_unavailable` as an external
live blocker; do not invent a value or claim ChatGPT generated/displayed the
ID. Perform only public `initialize`/`tools/list` discovery and copy the exact
production callback shown by app management. Then stop and remove TLS and the
named discovery backend before changing configuration:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  --profile public-tls stop public-tls
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  --profile public-tls rm -f public-tls
docker stop formowl-discovery-only
docker rm formowl-discovery-only
```

Finalize the ignored operator environment by replacing only the redirect
sentinel with the exact callback shown by ChatGPT. Keep
`FORMOWL_CHATGPT_CLIENT_ID` unchanged, then render Compose while no discovery
container is running:

```sh
FORMOWL_CHATGPT_REDIRECT_URI='https://chatgpt.com/connector/oauth/<callback-id>'
export FORMOWL_CHATGPT_REDIRECT_URI
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --network none \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  -v "$FORMOWL_OPERATOR_DIR:/operator" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  write-compose-env \
  --replace \
  --output /operator/compose.env \
  --project-name "$FORMOWL_PROJECT_NAME" \
  --runtime-image "$FORMOWL_RUNTIME_IMAGE" \
  --tls-proxy-image "$FORMOWL_TLS_PROXY_IMAGE" \
  --public-host "$FORMOWL_PUBLIC_HOST" \
  --acme-email "$FORMOWL_ACME_EMAIL" \
  --chatgpt-client-id "$FORMOWL_CHATGPT_CLIENT_ID" \
  --chatgpt-redirect-uri "$FORMOWL_CHATGPT_REDIRECT_URI" \
  --google-client-id "$FORMOWL_GOOGLE_CLIENT_ID" \
  --owner-bootstrap-operator-service-id \
    "$FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID"
printf '%s\n' 'FORMOWL_CADDYFILE=./.formowl/issue20/Caddyfile' \
  >> "$FORMOWL_COMPOSE_ENV"
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  config --format json > .test-tmp/issue20-compose-final.json
```

For either a direct exact callback or the finalized discovery flow, only now
start PostgreSQL, migrate, and run normal preflight:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  up -d postgres
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-migrate
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp preflight
```

Migration must complete before any bootstrap, invitation, token, or protected
MCP traffic.

The finalized preflight must report `status: ready` with database, schema,
configuration, signing key, Google OIDC metadata/JWKS, and upload-store checks
all true. Any other result is a stop condition. Do not start OAuth or work
around it with manual identity. Owner bootstrap remains forbidden until this
finalized preflight succeeds.

Record only safe status/count/hash evidence. Do not copy the DSN, schema SQL,
Google responses, secret paths, or private key material into the evidence
packet.

The repository's bounded clean-temp operator journey builds the current
runtime image, initializes an empty temporary secret directory through the
exact command above, proves an unchanged rerun, injects a synthetic Google
credential separately, starts a disposable PostgreSQL instance, and executes
the installed `formowl-connected-mcp` migration and lookup/list commands. Its
public report is limited to status, counts, hashes, and explicit attestations;
it is engineering evidence only and is not a substitute for the real Google,
TLS, MCP Inspector, or ChatGPT journeys later in this runbook.

### 3.1 Final Repository-Bound Operator and Lifecycle Evidence

Run all eight local campaign stages only after the issue #20 production,
runtime, container, migration, operator-command, documentation, evidence, and
final post-cleanup source snapshot are frozen. Before `preflight`, preserve any
scratch root from older source as non-authoritative history and perform the
governed reset required for the fixed active path. Any report produced before
that freeze is diagnostic and must not be reused as final evidence. A later
change to a bound source changes the current `implementation_contract_hash` and
makes the earlier operator/lifecycle report stale; preserve that stale campaign
before resetting and starting a fresh one.

The bound source set includes both containerized evidence-runner authority
files: `scripts/issue20_containerized_evidence_runner.sh` and
`scripts/issue20_runner_boundary.py`. A change to either file independently
stales the raw PostgreSQL/operator/lifecycle reports, their external layers,
the completion source, and the final packet. Rebuilding only a public layer or
editing a stored hash is not a substitute for rerunning the governed source
journeys through the changed runner authority.

The implementation-contract deploy boundary binds tracked
`Caddyfile.example`, `compose.env.example`, `operator_config.py`, secret setup
guidance, and the signing-key-set example. Ignored operator-local Caddy/env
copies are operational state, not frozen implementation authority. The real
BuildKit regression must prove that the current source and the frozen build
snapshot produce equal implementation-contract hashes before final evidence is
accepted.

First run and validate the clean-temp operator CLI/PostgreSQL journey through
the containerized evidence runner, then convert its schema-v2 report into the
current v2 external layer with explicit attestation. Keep the verifier-held
authority and pin at their fixed original paths for every command:

```sh
ISSUE20_SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$(id -u)"
OPERATOR_REPORT="$ISSUE20_SCRATCH_ROOT/reports/operator-postgresql.json"
OPERATOR_AUTHORITY="$ISSUE20_SCRATCH_ROOT/trust-inputs/operator-postgresql-execution-authority.json"
OPERATOR_AUTHORITY_PIN="$ISSUE20_SCRATCH_ROOT/trust-inputs/operator-postgresql-execution-authority-pin.json"

scripts/issue20_containerized_evidence_runner.sh preflight
scripts/issue20_containerized_evidence_runner.sh operator
scripts/issue20_containerized_evidence_runner.sh operator-layer
scripts/issue20_containerized_evidence_runner.sh live-postgresql
scripts/issue20_containerized_evidence_runner.sh lifecycle-a
scripts/issue20_containerized_evidence_runner.sh lifecycle-b
scripts/issue20_containerized_evidence_runner.sh lifecycle-aggregate
scripts/issue20_containerized_evidence_runner.sh local-harness
```

For direct raw-report revalidation and external-layer conversion, use the
`issue20_dev_with_scratch` helper defined in
`docs/issue20-oauth-evidence-runbook.md` and preserve both original trust
inputs exactly:

```sh
issue20_dev_with_scratch python \
  scripts/connected_operator_postgres_live_journey.py \
  --validate-report "$OPERATOR_REPORT" \
  --trusted-execution-authority "$OPERATOR_AUTHORITY" \
  --trusted-execution-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --output .test-tmp/issue20-operator-postgresql-validation.json
issue20_dev_with_scratch python scripts/oauth_mcp_harness.py \
  --operator-cli-postgresql-report "$OPERATOR_REPORT" \
  --operator-cli-postgresql-authority "$OPERATOR_AUTHORITY" \
  --operator-cli-postgresql-authority-pin "$OPERATOR_AUTHORITY_PIN" \
  --operator-attest-postgresql \
  --output .test-tmp/issue20-operator-postgresql-external-layer.json
```

The runner creates `trust-inputs` as mode `0700` and the two fixed files once
with exclusive creation and mode `0400`, before PostgreSQL or the raw inner
journey starts. They are outside `reports`; the reports directory is never the trust source.
The runner never removes, overwrites, or reconstructs them from a report. If
either path already exists, the operator campaign aborts before the raw journey.
If only one file is durable after a failed creation, leave it in place: the
partial pair locks that campaign. Do not create the missing peer or reuse either
artifact. Stop the campaign, perform a governed reset of the entire scratch root,
and start a fresh campaign.

Operator failure reporting uses two-stage diagnostic custody. The inner runtime
UID `10001` may write only an ephemeral private handoff, finalized at mode
`0444`, inside the journey's existing temporary directory. The outer process
validates its owner, mode, inode stability, exact closed schema, and finite
`inside_*` stage before creating the runner-owned mode `0400` final diagnostic
under `private-logs`. An invalid or missing handoff degrades only to
`outer_inner_journey`; it never forwards child stderr or private detail. A
successful inner run must leave no handoff. Only the fixed final diagnostic,
not the ephemeral handoff, locks the campaign until a governed scratch-root
reset.

The documented failure `stage` must be exactly one of:

```text
inside_migration
inside_operator_commands
inside_report
inside_runtime_setup
inside_seed
inside_verification
outer_authority
outer_inner_journey
outer_postgresql
outer_report
outer_runtime_cleanup
outer_runtime_setup
outer_secret_set
```

Only the generated operator schema-v2 report is eligible for an external or
completion claim. Its exact authority is ten successful CLI operations, three
denials, thirteen persisted operator audits (ten allowed and three denied),
one rollback probe with preserved state, and the complete bootstrap,
invitation, revocation, removal, and restore lifecycle. The standalone journey
validator may continue to read a schema-v1 diagnostic artifact, but the
external converter rejects it with `operator_evidence_schema_v2_required`.
Relabelling a v1 report, replacing its counts, or coherently recomputing a
public artifact hash does not upgrade it. The v2 external layer binds the exact
runtime IID, current journey script/report, pinned PostgreSQL image digest,
current v2 authority contract, rollback counts, and immutable-image
attestation. It remains hash/status/count/attestation only.

The operator journey itself builds with `--iidfile`, rejects anything other
than an exact `sha256:<64 lowercase hex>` ID before the first `docker run`, and
uses that IID for both secret initialization runs and the nested journey. Its
inside process receives the same value through `--runtime-image-id`,
`FORMOWL_OPERATOR_JOURNEY_RUNTIME_IMAGE_ID`, and a SHA-256 commitment to the IID
text; all three must agree. PostgreSQL uses only the pinned digest from section
2.

The runner modes create and validate the fixed raw reports
`operator-postgresql.json`, `live-postgresql.json`,
`production-lifecycle-a.json`, `production-lifecycle-b.json`, and
`local-oauth-harness.json` under `reports/`. They also derive the operator and
lifecycle public layers. Do not rename or replace these with similarly labelled
`.test-tmp` files. Run the governed packet commands in
`docs/issue20-oauth-evidence-runbook.md` through `formowl-dev:local`.

The raw `live-postgresql.json` authority is
`formowl_connected_runtime_postgres_live_e2e_v2`, with exact top-level fields
`artifact_id`, `status`, `protocol_version`, `metrics`, `safe_counts`,
`safe_hashes`, `live_postgresql_layer`, and `claim_boundary`. The report has no
standalone `schema_version` field. Do not substitute the obsolete
`formowl_connected_runtime_postgres_live_e2e_v1` artifact or a
`schema_version: 1` contract expectation.

The aggregator rejects duplicate runs, stale implementation/image/Compose
fingerprints, missing required secret bindings, count drift, failed SIGTERM or
database-release checks, and altered JWKS `1 -> 2 -> 1` evidence. Each run must
also bind the actual Compose migrate and preflight success, seven distinct
operator-owned mode-`0400` secret sources, three ready/healthy secret-snapshot
generations, two retired prior instances, the runtime UID `10001`, and the
Compose live-journey, security-contract, and secret-snapshot hashes. It emits a
public `run_report_set_hash` commitment to the sorted distinct private-report
hashes, then self-binds the complete v4 public lifecycle layer. Dedicated layer
validation and full packet validation both recompute that artifact binding.
Each lifecycle run captures one exact runtime IID, exports it to Compose as
`FORMOWL_RUNTIME_IMAGE`, exports the repository-pinned PostgreSQL digest as
`FORMOWL_POSTGRES_IMAGE`, and rejects rendered Compose unless both connected
services and PostgreSQL resolve to those immutable references.
Keep the two private lifecycle reports, the operator report, and any validation
detail in governed ignored operator state. Keep the original operator authority
and pin separately under `trust-inputs`, and pass those same paths explicitly to
review preparation, completion-audit preparation, packet build, and paired
packet validation as documented in `docs/issue20-oauth-evidence-runbook.md`.
Only the bounded external layers belong in the final packet.

After the live PostgreSQL rotation journey, bind its bounded safe source report
with `source_report_commitment_hash` and use the v3 public-layer artifact that
is recomputable from every public live-PostgreSQL field except the artifact
itself. Then complete the remaining real MCP Inspector and ChatGPT/Google
journeys and rerun the local OAuth harness against the final source and
documentation state. Assemble packet schema version `5` with the
`operator_cli_postgresql` layer and the exact operator, live-PostgreSQL, and
lifecycle completion-audit artifact bindings. A valid packet still does not
close issue #20 or establish production readiness; the independent completion
audit and reviewer gate remain required.

## 4. Bootstrap the First Owner

For an empty workspace, create exactly one time-limited owner invitation using
the authorized deployment operator id. If section 1.1 used discovery-only
callback bootstrap, do not run this command until the exact
`https://chatgpt.com/connector/oauth/{callback_id}` is configured and the
finalized one-off preflight reports `status: ready`. This is a
**deployment-operator shell action**, not a ChatGPT or end-user action:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp bootstrap-owner \
  --workspace-id <workspace-id> \
  --email <invited-owner-email> \
  --expires-at <RFC3339-expiry> \
  --idempotency-key <operator-generated-idempotency-key> \
  --operator-service-id <authorized-operator-service-id>
```

An identical retry must be idempotent. A different email, operator, or
incompatible invitation for the same bootstrap must fail closed. Bootstrap
creates no fake user or placeholder membership; the real user and owner
membership are created only after the invited person completes Google login.

## 5. Serve Behind TLS and Verify Readiness

Start the connected service only after migration, preflight, and bootstrap:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  --profile public-tls up -d --force-recreate connected-mcp public-tls
docker run --rm \
  --read-only \
  --entrypoint python \
  -v "$PWD:/workspace:ro" \
  "$FORMOWL_RUNTIME_IMAGE" \
  /workspace/deploy/connected/operator_config.py \
  check-public \
  --origin "https://$FORMOWL_PUBLIC_HOST" \
  --mode ready
```

Verify the private/public port boundary without a host networking utility:

```sh
test "$(
  docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
    port connected-mcp 8000
)" = "127.0.0.1:8000"
test -z "$(
  docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
    port postgres 5432 2>/dev/null || true
)"
```

Compose publishes FormOwl only on loopback. The operator-controlled
host-network `public-tls` service binds public ports 80/443 directly and has no
Compose `ports` mapping. Verify the public HTTPS paths through Caddy, not by
advertising the backend port:

```text
GET https://formowl.example.com/healthz -> 200 and status ok
GET https://formowl.example.com/readyz  -> 200 and status ready
GET protected /mcp without a token     -> OAuth challenge, not a tool result
```

After finalized public readiness, open the app in ChatGPT app management,
choose **Refresh**, verify the current tool list, and start a new conversation.
An old conversation is not callback/tool-metadata evidence.

The service must not accept manual identity variables, Google tokens as MCP
bearer tokens, caller-supplied user/workspace/session/grant fields, or an
alternate MCP resource URL.

## 6. First Real Google Owner Login

The deployment operator stops typing after the invitation/start commands.
These are **first-owner browser and ChatGPT actions** using the invited Google
account:

1. Start from the public HTTPS `/mcp` resource.
2. Follow the FormOwl authorization page and Google OIDC login.
3. Confirm that the exact invited email and verified Google `(issuer, subject)`
   bind to one FormOwl external identity.
4. Complete the FormOwl code exchange; do not capture or paste the code, PKCE
   verifier, Google token, or FormOwl bearer token.
5. Ask: `Use FormOwl whoami and summarize only my role and current workspace.`
   Verify only the real FormOwl user, owner role, and intended current
   workspace are returned.
6. Ask: `Use FormOwl to open a workspace-scoped upload session.` Confirm the
   FormOwl tool call. Verify its audit event carries the same user, external
   identity, OAuth client, token session, request/tool-call lineage, and
   workspace.

Every protected call must resolve a fresh `ActorContext` from current
PostgreSQL state. A successful `whoami` is not permission to bypass issue
#41's Asset authorization boundary.

## 7. Invite and Verify a Second User

Return to the **deployment-operator shell** only after the real owner exists.
Retrieve the owner's stable FormOwl user ID without temporary SQL:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp lookup-user \
  --email <owner-email> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

If the email maps to zero, multiple, disabled, or removed users, the lookup
fails closed. `list-users` is available when the operator needs the active
workspace membership list:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp list-users \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

The output contains stable user/workspace IDs, role, status, and counts only;
it omits email, display name, external-provider subject, storage paths, SQL, and
backend detail. Use the returned owner `user_id` to create a separate
invitation:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp invite-user \
  --workspace-id <workspace-id> \
  --email <second-user-email> \
  --role member \
  --invited-by-user-id <owner-user-id> \
  --operator-service-id <authorized-operator-service-id> \
  --expires-at <RFC3339-expiry>
```

The operator then hands control to the **second real user**. That person must
use a separate browser/ChatGPT account and their own invited Google account;
the owner must not complete the second user's login. In a new conversation,
enable the FormOwl app and ask:

```text
Use FormOwl whoami and summarize only my role and current workspace.
```

Verify it returns a FormOwl user distinct from the owner, role `member`, and
only the invited workspace. Probe an uninvited account, expired invitation,
mismatched email, and cross-workspace request; each must fail without creating
a usable token or partial membership. A schema-valid cross-workspace probe may
use `open_upload_session` with an `owner_scope_id` different from the current
workspace; it must reach FormOwl and be denied with zero semantic result and
zero partial state.

Every authorized allow or deny lookup is written as a service-attributed audit
event in the same database transaction. An operator-ID mismatch is recorded as
`external_unauthenticated`, not falsely attributed to the named service. If the
audit write fails, the CLI returns no lookup/list result.

## 8. Restart Persistence

Restart the connected service without replacing the PostgreSQL or FormOwl data
volumes:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  restart connected-mcp
```

After `/readyz` returns ready, verify both linked users, invitations,
memberships, client authorizations, token-session/revocation state, upload
session state, and OAuth audit lineage remain available. Existing unexpired,
unrevoked resource-bound tokens may continue only if all current authorization
state still passes; removed membership or disabled identity must fail on the
next call because `ActorContext` is rebuilt.

## 9. Revoke, Deny, and Relink

Obtain active token-session identifiers through the authorized local operator
view, never from raw token, bearer, JTI, or ad-hoc SQL material:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp list-token-sessions \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

The list returns active stable token-session IDs plus issue/expiry timestamps
and counts. It never returns bearer tokens, token/JTI hashes, provider subjects,
client secrets, scopes, resource URLs, raw paths, SQL, or backend details. If
exactly one active session is expected, require that invariant explicitly:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp lookup-token-session \
  --user-id <user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Zero or multiple active sessions, disabled users or identities, revoked client
authorization, removed membership, invalid identifiers, and inconsistent
lineage fail closed. Both allow and deny results require a committed audit.
Select the intended returned ID and revoke it as exactly one authority:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp revoke-token-session \
  --token-session-id <token-session-id> \
  --reason-code operator_test_revocation \
  --operator-service-id <authorized-operator-service-id>
```

Immediately repeat `whoami` or another protected tool with the existing client
session. It must receive an OAuth denial/challenge and no semantic result. The
old token session must remain unusable after service restart.

Reconnect through the complete FormOwl OAuth and Google OIDC flow. Verify a new
token session is created, `whoami` succeeds for the same `(issuer, subject)`,
and the revoked session still fails.

Run expiry/relink as a separate real-time journey. The production access-token
lifetime is fixed at exactly 3600 seconds and token validation uses a fixed
30-second clock skew. There is no supported operator setting for a shorter
access-token lifetime; do not change configuration, patch code, or move clocks
to accelerate this evidence:

1. Complete a new FormOwl OAuth and Google flow and call `whoami`.
2. Immediately use `list-token-sessions` or `lookup-token-session` to bind the
   new stable token-session ID, `issued_at`, and `expires_at`. Require
   `expires_at - issued_at` to equal exactly 3600 seconds.
3. Preserve that ChatGPT app session without refreshing or reconnecting.
4. Set `EXPIRES_AT` to the exact safe RFC 3339 expiry returned by the operator
   view and use the immutable runtime image's standard-library helper to wait
   until trusted UTC is strictly later than `expires_at + 30 seconds`:

   ```sh
   EXPIRES_AT='<exact-RFC3339-expires_at>'
   docker run --rm \
     --read-only \
     --network none \
     --entrypoint python \
     -v "$PWD:/workspace:ro" \
     "$FORMOWL_RUNTIME_IMAGE" \
     /workspace/deploy/connected/operator_config.py \
     wait-until-expired \
     --expires-at "$EXPIRES_AT"
   ```

5. Reuse the unchanged app session for `whoami` or another protected tool. It
   must receive an OAuth denial/challenge with zero semantic results and zero
   state writes.
6. Reconnect through the full FormOwl OAuth and Google flow. Require a new
   token-session ID, successful `whoami`, and continued denial of the expired
   session. Expiry must never silently extend or reactivate the old session.

Exercise membership removal independently from one-session revocation. Never
remove the last active owner; that command must fail closed with a committed
service-attributed denial audit:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp remove-workspace-member \
  --user-id <second-user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Removal preserves the membership row with `removed_at`, revokes every
unrevoked token session for that user/workspace with reason
`workspace_membership_removed`, and commits the mutation and allow audit in one
transaction. Verify the existing protected session fails immediately and still
fails after restarting `connected-mcp`. Then restore the same historical
membership row:

```sh
docker compose --file compose.yaml --env-file "$COMPOSE_ENV" \
  run --rm connected-mcp restore-workspace-member \
  --user-id <second-user-id> \
  --workspace-id <workspace-id> \
  --operator-service-id <authorized-operator-service-id>
```

Restore does not reactivate old token sessions. The user must complete the full
FormOwl OAuth and Google OIDC flow again; verify the same external identity and
FormOwl user receive a new token-session ID, the new session succeeds, and the
pre-removal session remains revoked. If either membership mutation's audit
write fails, the membership and token-session mutation must roll back and the
CLI must return no success result.

## 10. Signing-Key Rotation

Rotate FormOwl signing keys without invalidating still-valid tokens abruptly:

1. Start from the unused standby mount slot or generate a new private key
   outside the repository and place it in the inactive mount slot.
2. Update `signing-key-set.json` so that key is the sole `active: true` key.
3. Keep the formerly active key mounted and list it as `active: false` with
   `verify_until` later than the maximum remaining fixed 3600-second token
   lifetime, fixed 30-second clock skew, and deployment overlap window.
4. Run
   `docker compose --file compose.yaml --env-file "$COMPOSE_ENV" run
   --rm connected-mcp preflight`; stop if the manifest, active key, database,
   or Google checks fail.
5. Recreate or restart `connected-mcp`, wait for public `/readyz`, and verify
   `/.well-known/jwks.json` publishes both the new signing key and the still
   valid previous verification key.
6. Complete a new login and protected tool call. Newly issued FormOwl tokens
   must use the new active key; an unexpired old token may verify only during
   its declared overlap window.
7. After `verify_until` and every possible old-token lifetime have elapsed,
   remove the previous key from the manifest and secret mounts, rerun preflight,
   restart, and confirm JWKS no longer publishes it.

Never reuse a key id, keep two active keys, remove the previous key before the
grace window, or print private keys/token contents while verifying rotation.

## 11. Remote MCP Inspector Journey

Prerequisites are Node.js with `npx` and the already reachable public HTTPS
FormOwl `/mcp` endpoint. Use the official OpenAI-documented launcher from a
separate operator shell; do not add Node.js, Inspector, or its dependencies to
the FormOwl runtime image:

```sh
npx @modelcontextprotocol/inspector@latest
```

Record a hash commitment to the resolved Inspector package version shown by the
launcher, then point the UI at the public
`https://formowl.example.com/mcp` resource. Stop the Inspector with Ctrl+C
after the bounded sequence below.

The general OpenAI testing guide permits Inspector OAuth debugging, but this
closed beta deliberately has one predefined OAuth client: ChatGPT. Therefore
Inspector must not register or become a second OAuth client. Do not enable
CIMD or DCR for Inspector, do not complete Google login in Inspector, do not
use Inspector's Auth flow, and do not paste a real bearer token.

The governed Inspector evidence is limited to this exact public-only sequence:

1. Enter the public HTTPS FormOwl `/mcp` URL and complete public MCP
   `initialize`; record a commitment to the negotiated protocol version and
   response shape.
2. Choose **List Tools** and record a commitment to the public `tools/list`
   shape. Verify each protected tool declares `securitySchemes`, the required
   Apps SDK `_meta` mirror is present where applicable, and no backend detail
   is exposed.
3. Choose **Call Tool** for one protected tool without authenticating. It must
   return an OAuth challenge with `_meta["mcp/www_authenticate"]`, including
   `error` and `error_description`, and no semantic result or partial state.
4. Send one fixed, non-secret synthetic invalid-bearer probe. It must receive
   the same protected-resource challenge and still create no semantic result or
   partial state. Never copy a real FormOwl or Google token into Inspector.
5. Confirm the Inspector artifact contains only the public initialization,
   tool-list, protected-challenge, invalid-bearer-challenge, version, count,
   status, and hash commitments.

Inspector must not claim OAuth login, `whoami`, `open_upload_session`, Google
callback, authenticated tools, identity forgery, cross-workspace denial,
membership changes, revocation, or relink evidence. Those journeys belong only
to section 12. If Inspector authentication is attempted, discard that
Inspector source and rerun the public-only sequence from a clean session.

## 12. Real ChatGPT and Google Journey

Enable and create the developer-mode app through ChatGPT Apps management. UI
labels can move, so use the official OpenAI references at the start of this
runbook and do not rely on the obsolete Plugins navigation label:

1. Open <https://chatgpt.com>, then choose **Settings → Security and login**
   and enable **Developer mode**. If the control is unavailable, stop and ask
   the workspace administrator to permit it.
2. During section 3, open ChatGPT Apps management, create or refresh the
   developer-mode app, use the reachable public HTTPS FormOwl `/mcp` URL, and
   configure the same operator-recorded predefined client ID if that choice is
   available. If the choice is unavailable, stop and record the external live
   blocker rather than continuing or inventing an ID.
3. Follow the redirect-sentinel discovery procedure in section 1.1. Do not
   bootstrap an owner or start OAuth while the reserved redirect is configured.
4. After the exact callback is configured, restart FormOwl, rerun preflight,
   wait for `/readyz`, open the app in ChatGPT Apps management, and choose
   **Refresh**. Verify the refreshed tool list before continuing.
5. Open a new conversation, choose **+ → More**, and enable the FormOwl app for
   that conversation. Metadata changes require another **Refresh** and another
   new conversation; an already-open conversation is not accepted as refreshed
   evidence.

Run the authenticated owner, second-user, denial, and relink journeys only in
this real ChatGPT app plus Google layer:

```text
public discovery and protected-tool OAuth challenge
-> real Google authorization and callback
-> FormOwl token exchange
-> whoami
-> open_upload_session
-> invite and link a second real Google user as workspace member
-> second-user whoami
-> owner-only invitation approval denial through controlled operator CLI
-> cross-workspace denial
-> caller-identity forgery request reaches the FormOwl Gateway and is denied
-> remove second-user membership and verify immediate plus post-restart denial
-> denied relink while membership is removed creates no code/session/membership
-> restore membership, relink the same subject/user into a new session
-> verify the pre-removal session remains denied
-> revoke token session
-> revoked-token denial
-> reconnect through Google
-> whoami with a new token session
-> expire and deny the new token
-> reconnect and verify whoami again
```

The owner-only denial is not an MCP tool. Run `invite-user` from the controlled
deployment shell with the authorized operator service but attribute approval to
the second user's member `user_id`. The request must fail with
`invitation_owner_required`; its audit actor is the operator service, while a
safe commitment records the member approval attribution. It must have no MCP
tool-call binding. Do not invent an `owner_only` MCP tool to satisfy the
journey.

The identity-forgery request counts only if it reaches the FormOwl Gateway and
a server-side denied audit record is committed. A ChatGPT client-side schema
error or model refusal before the request reaches FormOwl is useful diagnostic
feedback but is not forgery-denial evidence. Cross-workspace and owner-only
denials must remain separately committed and must not reuse one observation.

The final live source must preserve the exact 47-row safe audit manifest in
order. Every row has a distinct `audit_record_hash`, binds every safe row field,
and carries `previous_audit_record_hash` equal to the preceding row's hash.
Service operations must not be falsely attributed to the owner user. All
denials must return zero semantic results and zero partial-state writes.

After the final journey action is complete, use the connected runtime's
operator-only exporter instead of querying PostgreSQL manually. First create a
private directory in the persistent data volume as the runtime service user:

```sh
docker compose run --rm --no-deps \
  --user 10001:10001 \
  --entrypoint /bin/sh \
  connected-mcp \
  -c 'umask 077; install -d -m 0700 /data/operator-evidence'
```

Then provide the exact UTC window that begins before owner bootstrap and ends
after the final post-expiry `whoami` audit:

```sh
docker compose run --rm connected-mcp \
  export-issue20-live-audit \
  --workspace-id "$FORMOWL_ISSUE20_WORKSPACE_ID" \
  --started-at "$FORMOWL_ISSUE20_AUDIT_STARTED_AT" \
  --ended-at "$FORMOWL_ISSUE20_AUDIT_ENDED_AT" \
  --operator-service-id "$FORMOWL_OWNER_BOOTSTRAP_OPERATOR_SERVICE_ID" \
  --output /data/operator-evidence/issue20-live-audit.json
```

The command reads only the allowlisted Issue #20 audit actions in that bounded
window and fails closed unless it can reconstruct the exact 47-event lineage,
five distinct token sessions, two distinct linked users/identities, required
service attribution, and complete hash chain. The private file is replaced
atomically at mode `0600`. Standard output contains only `status`,
`audit_record_count`, and `audit_manifest_hash`; errors contain only the generic
export code. Do not paste the private file, its path, database configuration, or
any raw audit row into public evidence.

Capture only bounded status/count/hash evidence and operator attestations. Do
not paste raw ChatGPT transcripts, tool payloads, email addresses, identifiers,
tokens, callbacks with codes, secret values, paths, or database detail into the
public packet. Use `docs/issue20-oauth-evidence-runbook.md` for the packet
contract and independent completion-audit boundary.

## 13. Governed Final Closure Handoff

After all seven external layers are `passed`, the packet pair-validation has
zero blockers, the final external-packet-bound harness and its validation pass,
the Issue-wide reviewer layer is exactly 3/3 `AGREE`, and the distinct
independent completion auditor passes, follow the exact **Governed final
closure transition** section in `docs/issue20-oauth-evidence-runbook.md`.

The ordering is mandatory: build and validate
`.test-tmp/issue20-preclosure-manifest.json`; apply the exact governed
transition to the five completion-state documents; then build and validate
`.test-tmp/issue20-completion-transition.json`. Stop on any failed command,
blocker, drifted packet/pin/hash, partial document update, Issue #41 change, or
expanded production-readiness claim. Do not improvise flags or substitute
similarly named artifacts.

Finalization computation faults, including implementation-contract computation
faults, are generic failed validations. They must not leak exception,
filesystem, filename, or computation detail, must not escape uncaught, and
must not replace prior output bytes. The strengthened regression and onboarding
manifest update are included in the verified 508-test harness authority.

The validated completion-transition artifact does not commit or push Git
changes and does not close GitHub Issue #20. Those remain separate operator
publication actions that require clean reconciliation of the shared source
state and explicit authorization. Until those publication conditions are met,
keep GitHub Issue #20 open.

## Offline Compatibility Regression

The older synthetic backbone smoke remains useful, but it is not the connected
identity or live closed-beta gate:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace formowl-dev:local \
  python scripts/closed_beta_smoke.py --output /tmp/formowl-closed-beta-smoke.json
```

It exercises Project/Wiki JSON-RPC compatibility, synthetic ingestion,
retrieval grants, proposal-only wiki behavior, and KG-eval integration. It does
not prove public HTTPS, OAuth, Google login, PostgreSQL restart persistence,
signing-key rotation, MCP Inspector, live ChatGPT, issue #20 closure, or
production readiness.

## Completion and Issue Boundaries

The live steps above are evidence collection instructions, not a statement that
they have already passed. Issue #20 remains open until the required external
packet, documentation state, canonical checks, and configured reviewer gate
all agree with no blockers.

Issue #20 establishes connected identity and fresh `ActorContext`. Issue #41
separately owns generic Asset tenant/owner binding, byte storage, occurrence
lineage, upload recovery, lifecycle, retention, purge, and authorization.
Issue #21 is a downstream mail-evidence consumer of issue #41 and does not
create a separate identity or connected transport path.

Issue #20 completion requires that the gateway-controlled `ActorContext`
contract is verified and consumable by issue #41. It does not require issue
#41's planning-only storage implementation to be completed.

No result from this runbook alone claims automatic wiki publishing, general
mail/parser readiness, raw asset content access, canonical graph/type writes,
enterprise scalability or quality, top-tier scientific validation, security
certification, or product production readiness.
