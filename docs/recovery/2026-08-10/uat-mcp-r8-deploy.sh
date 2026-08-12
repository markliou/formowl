#!/usr/bin/env bash
# INTERNAL DIAGNOSTIC UAT ONLY.
#
# This is a bounded replacement for the legacy single-sidecar launch plan.  It
# starts four containers:
#   1. one existing read-only FormOwl diagnostic MCP,
#   2. one private no-web Codex planner,
#   3. one public web-only Codex terminology grounder, and
#   4. the local browser UAT HTTP surface.
#
# The public web container receives only its own runtime state, socket,
# explicitly approved frozen tokenizer, and the public ontology via the UAT
# transport.  It never mounts the private root, bridge, corpus, manifest,
# diagnostic-MCP command file, or a private semantic profile.
#
# The script is intentionally diagnostic-only.  It does not build images,
# reparse mail archives, write a canonical KG, perform a browser acceptance
# claim, or make a production-readiness claim.
set -Eeuo pipefail
IFS=$'\n\t'

PLAN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ACTION=""
IMAGE=""
PRIVATE_ROOT=""
BRIDGE_ROOT=""
WORKTREE_ROOT=""
RUNTIME_TOOLS_ROOT=""
AUTH_CACHE=""
RUNTIME_ROOT=""
DIAGNOSTIC_COMMAND_JSON=""
CORPUS_ROOT_HOST=""
PRIVATE_MANIFEST_HOST=""
CODEX_COMMAND="codex"
HOST_PORT="8088"
MCP_HOST_PORT="8091"
TOKENIZER_MODEL=""
TOKENIZER_SHA256=""
PUBLIC_ONTOLOGY="$PLAN_DIR/public-semantic-ontology-v1.json"

CORE_NETWORK="formowl-diagnostic-uat"
PRIVATE_CODEX_NETWORK="formowl-diagnostic-uat-private-codex"
WEB_CODEX_NETWORK="formowl-diagnostic-uat-public-web"
MCP_CONTAINER="formowl-diagnostic-mcp-uat"
PRIVATE_CODEX_CONTAINER="formowl-uat-private-codex"
WEB_CODEX_CONTAINER="formowl-uat-public-web-codex"
UAT_CONTAINER="formowl-mail-diagnostic-uat"

TOKENIZER_CONTAINER_PATH="/tokenizer/sentencepiece.model"
PRIVATE_STATE_CONTAINER_PATH="/formowl/runtime/private-codex-state"
WEB_STATE_CONTAINER_PATH="/formowl/runtime/public-web-codex-state"
UAT_STATE_CONTAINER_PATH="/formowl/runtime/uat-state"
PRIVATE_SOCKET_CONTAINER_PATH="/formowl/run/private-codex/private.sock"
WEB_SOCKET_CONTAINER_PATH="/formowl/run/public-web-codex/web.sock"
PUBLIC_ONTOLOGY_CONTAINER_PATH="/formowl/public/public-semantic-ontology-v1.json"
WORKTREE_PYTHON_CONTAINER_PATH="/opt/formowl/python"
CODEX_ENGINE_CONTAINER_PATH="/opt/formowl/scripts/mail_human_uat_codex_engine.py"
UAT_LAUNCHER_CONTAINER_PATH="/opt/formowl/scripts/mail_human_uat.py"
CORPUS_ROOT_IN_CONTAINER="/formowl/corpus"
PRIVATE_MANIFEST_IN_CONTAINER="/formowl/manifest/domain-hard-case-manifest.private.json"

PRIVATE_STATE_HOST=""
WEB_STATE_HOST=""
UAT_STATE_HOST=""
PRIVATE_SOCKET_DIR_HOST=""
WEB_SOCKET_DIR_HOST=""
WORKTREE_PYTHON_HOST=""
CODEX_ENGINE_HOST=""
UAT_LAUNCHER_HOST=""
RUN_UID=""
RUN_GID=""
declare -a DIAGNOSTIC_COMMAND=()
declare -a RUNTIME_TOOL_MOUNT_ARGS=()
declare -a WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS=()

# These are Python runtime implementation dependencies of the already-reviewed
# diagnostic adapter.  They are not business vocabulary and are mounted only
# into the diagnostic MCP container.
readonly DIAGNOSTIC_RUNTIME_TOOL_FILES=(
  "formowl_diagnostic_mcp_sharded.py"
  "diagnostic_structural_projection.py"
  "reviewed_structural_bindings.py"
  "diagnostic_current_export_table_snapshot.py"
  "diagnostic_xlsx_attachment_augmentation.py"
  "formowl_materialize_reviewed_bindings_private.py"
  "r8_source_only_ledgers.py"
)

# Mount only the current integration modules that differ from the diagnostic
# image.  The complete base-image package remains visible for every other
# dependency; no recovery source tree is imported or mounted.
readonly WORKTREE_PYTHON_OVERLAY_FILES=(
  "formowl_contract/__init__.py"
  "formowl_contract/structured_intent.py"
  "formowl_mail/diagnostic_mcp.py"
  "formowl_mail/human_uat_http.py"
  "formowl_mail/human_uat_orchestrator.py"
)

fail() {
  printf '%s\n' "FAIL: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage:
  uat-mcp-r8-deploy.sh dry-run [options]
  uat-mcp-r8-deploy.sh start [options]
  uat-mcp-r8-deploy.sh status
  uat-mcp-r8-deploy.sh stop

Required for dry-run and start:
  --image IMAGE
  --private-root ABSOLUTE_DIRECTORY
  --bridge-root ABSOLUTE_DIRECTORY
  --worktree-root ABSOLUTE_DIRECTORY
  --runtime-tools-root ABSOLUTE_DIRECTORY
  --auth-cache ABSOLUTE_FILE
  --runtime-root ABSOLUTE_DIRECTORY
  --diagnostic-command-json ABSOLUTE_FILE
  --corpus-root-host ABSOLUTE_DIRECTORY
  --private-manifest-host ABSOLUTE_FILE
  --tokenizer-model ABSOLUTE_FILE
  --tokenizer-sha256 SHA256_HEX

Optional:
  --public-ontology ABSOLUTE_FILE
  --codex-command COMMAND                      (default: codex)
  --host-port PORT                             (default: 8088)
  --mcp-host-port PORT                         (default: 8091)

The diagnostic command file is an operator-private JSON array of executable
arguments for the already-reviewed diagnostic MCP.  It is never mounted into
or supplied to either Codex sidecar.  It must not use shell execution.  The
launcher mounts the current worktree's Python package read-only at
/opt/formowl/python only as an allowlisted per-file overlay.  All other Python
dependencies remain from the complete base-image package.  It mounts only the
exact current sidecar/UAT launcher files needed by their respective containers.
EOF
}

require_absolute_path() {
  local value="$1"
  local label="$2"
  [[ "$value" == /* ]] || fail "$label must be absolute"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "$label is invalid"
}

require_regular_file() {
  local value="$1"
  local label="$2"
  require_absolute_path "$value" "$label"
  [[ -f "$value" && ! -L "$value" ]] || fail "$label must be a regular non-symlink file"
}

require_directory() {
  local value="$1"
  local label="$2"
  require_absolute_path "$value" "$label"
  [[ -d "$value" && ! -L "$value" ]] || fail "$label must be a directory and not a symlink"
}

require_port() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "$label must be numeric"
  (( value >= 1 && value <= 65535 )) || fail "$label is out of range"
}

sha256_file() {
  sha256sum -- "$1" | awk '{print $1}'
}

validate_tokenizer() {
  [[ -n "$TOKENIZER_MODEL" ]] || fail "--tokenizer-model is required"
  [[ "$TOKENIZER_SHA256" =~ ^[0-9a-f]{64}$ ]] ||
    fail "--tokenizer-sha256 must be a lowercase SHA-256 hex digest"
  require_regular_file "$TOKENIZER_MODEL" "tokenizer model"
  [[ "$(sha256_file "$TOKENIZER_MODEL")" == "$TOKENIZER_SHA256" ]] ||
    fail "tokenizer model SHA256 does not match the approved frozen artifact"
}

validate_public_ontology() {
  require_regular_file "$PUBLIC_ONTOLOGY" "public semantic ontology"
  python3 - "$PUBLIC_ONTOLOGY" <<'PY'
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
try:
    raw = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"public ontology is unreadable: {type(exc).__name__}")

expected = {
    "ontology_revision",
    "provenance",
    "object_aliases",
    "predicate_aliases",
    "value_aliases",
    "value_domains",
}
if not isinstance(raw, dict) or set(raw) != expected:
    raise SystemExit("public ontology fields are invalid")
if not isinstance(raw["ontology_revision"], str) or not raw["ontology_revision"].strip():
    raise SystemExit("public ontology revision is invalid")
if not isinstance(raw["provenance"], str) or not raw["provenance"].strip():
    raise SystemExit("public ontology provenance is invalid")

def require_canonical_labels_only(mapping, label):
    if not isinstance(mapping, dict) or not mapping:
        raise SystemExit(f"{label} are invalid")
    for canonical, forms in mapping.items():
        if (
            not isinstance(canonical, str)
            or not canonical.strip()
            or not isinstance(forms, list)
            or forms != [canonical]
        ):
            raise SystemExit(f"{label} must contain canonical labels only")

require_canonical_labels_only(raw["object_aliases"], "object aliases")
require_canonical_labels_only(raw["predicate_aliases"], "predicate aliases")
if not isinstance(raw["value_aliases"], dict):
    raise SystemExit("value aliases are invalid")
if not isinstance(raw["value_domains"], dict):
    raise SystemExit("value domains are invalid")
for predicate, values in raw["value_aliases"].items():
    if predicate not in raw["predicate_aliases"]:
        raise SystemExit("value aliases reference an unknown predicate")
    require_canonical_labels_only(values, "value aliases")
if set(raw["value_domains"]) != set(raw["predicate_aliases"]):
    raise SystemExit("value domains must cover every predicate")
for predicate, domain in raw["value_domains"].items():
    if domain not in {"closed_enum", "open_public_value"}:
        raise SystemExit("value domain is invalid")
    has_enumerated_values = predicate in raw["value_aliases"]
    if domain == "closed_enum" and not has_enumerated_values:
        raise SystemExit("closed value domain requires value aliases")
    if domain == "open_public_value" and has_enumerated_values:
        raise SystemExit("open value domain must not enumerate values")

serialized = json.dumps(raw, ensure_ascii=False).casefold()
for forbidden in (
    "@",
    "mailto:",
    "file:",
    "/formowl/private",
    "source_observation_id",
    "message_id",
):
    if forbidden in serialized:
        raise SystemExit("public ontology contains prohibited private or alias content")
PY
}

load_diagnostic_command() {
  require_regular_file "$DIAGNOSTIC_COMMAND_JSON" "diagnostic command JSON"
  mapfile -d '' -t DIAGNOSTIC_COMMAND < <(
    python3 - "$DIAGNOSTIC_COMMAND_JSON" <<'PY'
import json
from pathlib import Path
import sys

try:
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"diagnostic command JSON is unreadable: {type(exc).__name__}")
if (
    not isinstance(raw, list)
    or not raw
    or any(
        not isinstance(item, str)
        or not item
        or len(item) > 4096
        or "\x00" in item
        or "\n" in item
        or "\r" in item
        for item in raw
    )
):
    raise SystemExit("diagnostic command JSON must be a bounded string array")
if raw[0] in {"sh", "bash", "dash", "zsh"} or "-c" in raw:
    raise SystemExit("diagnostic command must not use a shell")
for item in raw:
    sys.stdout.buffer.write(item.encode("utf-8") + b"\0")
PY
  ) || fail "diagnostic command JSON is invalid"
  (( ${#DIAGNOSTIC_COMMAND[@]} > 0 )) || fail "diagnostic command is empty"
}

validate_worktree_launchers() {
  local relative_path
  require_directory "$WORKTREE_ROOT" "worktree root"
  WORKTREE_PYTHON_HOST="$WORKTREE_ROOT/python"
  CODEX_ENGINE_HOST="$WORKTREE_ROOT/scripts/mail_human_uat_codex_engine.py"
  UAT_LAUNCHER_HOST="$WORKTREE_ROOT/scripts/mail_human_uat.py"
  require_directory "$WORKTREE_PYTHON_HOST" "worktree Python package"
  require_regular_file "$CODEX_ENGINE_HOST" "worktree Codex sidecar launcher"
  require_regular_file "$UAT_LAUNCHER_HOST" "worktree UAT launcher"
  WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS=()
  for relative_path in "${WORKTREE_PYTHON_OVERLAY_FILES[@]}"; do
    require_regular_file \
      "$WORKTREE_PYTHON_HOST/$relative_path" \
      "worktree Python overlay"
    WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS+=(
      --mount
      "type=bind,src=${WORKTREE_PYTHON_HOST}/${relative_path},dst=${WORKTREE_PYTHON_CONTAINER_PATH}/${relative_path},readonly"
    )
  done
}

validate_runtime_tool_mounts() {
  local file
  require_directory "$RUNTIME_TOOLS_ROOT" "runtime tools root"
  RUNTIME_TOOL_MOUNT_ARGS=()
  for file in "${DIAGNOSTIC_RUNTIME_TOOL_FILES[@]}"; do
    require_regular_file "$RUNTIME_TOOLS_ROOT/$file" "diagnostic runtime tool"
    RUNTIME_TOOL_MOUNT_ARGS+=(
      --mount
      "type=bind,src=${RUNTIME_TOOLS_ROOT}/${file},dst=/opt/formowl/scripts/${file},readonly"
    )
  done
}

validate_configuration() {
  [[ -n "$IMAGE" ]] || fail "--image is required"
  require_directory "$PRIVATE_ROOT" "private root"
  require_directory "$BRIDGE_ROOT" "bridge root"
  validate_worktree_launchers
  validate_runtime_tool_mounts
  require_regular_file "$AUTH_CACHE" "Codex auth cache"
  require_directory "$RUNTIME_ROOT" "runtime root"
  require_directory "$CORPUS_ROOT_HOST" "corpus root host"
  require_regular_file "$PRIVATE_MANIFEST_HOST" "private manifest host"
  [[ "$CODEX_COMMAND" != *$'\n'* && "$CODEX_COMMAND" != *$'\r'* && -n "$CODEX_COMMAND" ]] ||
    fail "Codex command is invalid"
  require_port "$HOST_PORT" "host port"
  require_port "$MCP_HOST_PORT" "MCP host port"
  [[ "$HOST_PORT" != "$MCP_HOST_PORT" ]] || fail "UAT and MCP host ports must differ"
  validate_tokenizer
  validate_public_ontology
  load_diagnostic_command
  RUN_UID="$(id -u)"
  RUN_GID="$(id -g)"
  (( RUN_UID != 0 )) || fail "the UAT launcher must run as a non-root user"
  PRIVATE_STATE_HOST="$RUNTIME_ROOT/private-codex-state"
  WEB_STATE_HOST="$RUNTIME_ROOT/public-web-codex-state"
  UAT_STATE_HOST="$RUNTIME_ROOT/uat-state"
  PRIVATE_SOCKET_DIR_HOST="$RUNTIME_ROOT/private-codex-socket"
  WEB_SOCKET_DIR_HOST="$RUNTIME_ROOT/public-web-codex-socket"
}

print_dry_run() {
  local ontology_revision
  local ontology_sha256
  ontology_revision="$(
    python3 - "$PUBLIC_ONTOLOGY" <<'PY'
import json
from pathlib import Path
import sys

print(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["ontology_revision"])
PY
  )" || fail "public ontology revision could not be read"
  ontology_sha256="$(sha256_file "$PUBLIC_ONTOLOGY")"
  printf '%s\n' "FORMOWL_DIAGNOSTIC_UAT_CONFIG_VALID"
  printf '%s\n' "containers=diagnostic-mcp,private-no-web-codex,public-web-only-codex,uat-http"
  printf '%s\n' "tokenizer_sha256=sha256:${TOKENIZER_SHA256}"
  printf '%s\n' "public_ontology_revision=${ontology_revision}"
  printf '%s\n' "public_ontology_sha256=sha256:${ontology_sha256}"
  printf '%s\n' "public_web_mounts=runtime-state,socket,approved-tokenizer"
  printf '%s\n' "public_web_private_mounts=none"
  printf '%s\n' "private_planner_network=isolated-bridge-egress"
  printf '%s\n' "private_planner_web_search=disabled"
  printf '%s\n' "worktree_python_overlay_count=${#WORKTREE_PYTHON_OVERLAY_FILES[@]}"
  printf '%s\n' "diagnostic_runtime_tool_mount_count=${#DIAGNOSTIC_RUNTIME_TOOL_FILES[@]}"
  printf '%s\n' "uat_corpus_and_manifest_mounts=readonly"
  printf '%s\n' "diagnostic_mcp_command_arguments=${#DIAGNOSTIC_COMMAND[@]}"
}

prepare_runtime_paths() {
  local path
  for path in \
    "$PRIVATE_STATE_HOST" \
    "$WEB_STATE_HOST" \
    "$UAT_STATE_HOST" \
    "$PRIVATE_SOCKET_DIR_HOST" \
    "$WEB_SOCKET_DIR_HOST"; do
    [[ ! -e "$path" ]] || fail "runtime path already exists; choose a new empty --runtime-root"
  done
  for path in \
    "$PRIVATE_STATE_HOST" \
    "$WEB_STATE_HOST" \
    "$UAT_STATE_HOST" \
    "$PRIVATE_SOCKET_DIR_HOST" \
    "$WEB_SOCKET_DIR_HOST"; do
    mkdir -p -- "$path"
    chmod 700 -- "$path"
  done
}

ensure_network() {
  local network
  for network in "$CORE_NETWORK" "$PRIVATE_CODEX_NETWORK" "$WEB_CODEX_NETWORK"; do
    if ! docker network inspect "$network" >/dev/null 2>&1; then
      docker network create "$network" >/dev/null
    fi
  done
}

assert_container_absent() {
  local container="$1"
  ! docker container inspect "$container" >/dev/null 2>&1 ||
    fail "container already exists: $container; use stop first"
}

init_sidecar_state() {
  local role="$1"
  local host_state="$2"
  local container_state="$3"
  cat -- "$AUTH_CACHE" | docker run --rm -i \
    --user "${RUN_UID}:${RUN_GID}" \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    --mount "type=bind,src=${host_state},dst=${container_state}" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${CODEX_ENGINE_HOST},dst=${CODEX_ENGINE_CONTAINER_PATH},readonly" \
    --mount "type=bind,src=${TOKENIZER_MODEL},dst=${TOKENIZER_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    -e FORMOWL_MAIL_TOKENIZER_MODE=jieba_sentencepiece_frozen \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL=${TOKENIZER_CONTAINER_PATH}" \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256=sha256:${TOKENIZER_SHA256}" \
    "$IMAGE" \
    python3 "$CODEX_ENGINE_CONTAINER_PATH" init \
      --state-dir "$container_state" \
      --runtime-role "$role" \
      --chatgpt-auth-stdin \
      --codex-command "$CODEX_COMMAND" >/dev/null
}

start_sidecar() {
  local container="$1"
  local network="$2"
  local role="$3"
  local host_state="$4"
  local container_state="$5"
  local host_socket_dir="$6"
  local container_socket="$7"
  docker run --detach --name "$container" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$network" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    --mount "type=bind,src=${host_state},dst=${container_state}" \
    --mount "type=bind,src=${host_socket_dir},dst=$(dirname -- "$container_socket")" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${CODEX_ENGINE_HOST},dst=${CODEX_ENGINE_CONTAINER_PATH},readonly" \
    --mount "type=bind,src=${TOKENIZER_MODEL},dst=${TOKENIZER_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    -e FORMOWL_MAIL_TOKENIZER_MODE=jieba_sentencepiece_frozen \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL=${TOKENIZER_CONTAINER_PATH}" \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256=sha256:${TOKENIZER_SHA256}" \
    "$IMAGE" \
    python3 "$CODEX_ENGINE_CONTAINER_PATH" serve \
      --state-dir "$container_state" \
      --runtime-role "$role" \
      --socket-path "$container_socket" \
      --codex-command "$CODEX_COMMAND" >/dev/null
}

start_diagnostic_mcp() {
  docker run --detach --name "$MCP_CONTAINER" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$CORE_NETWORK" \
    --publish "127.0.0.1:${MCP_HOST_PORT}:8090" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=${PRIVATE_ROOT},dst=/formowl/private,readonly" \
    --mount "type=bind,src=${BRIDGE_ROOT},dst=/formowl/bridge,readonly" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${TOKENIZER_MODEL},dst=${TOKENIZER_CONTAINER_PATH},readonly" \
    "${RUNTIME_TOOL_MOUNT_ARGS[@]}" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    -e FORMOWL_MAIL_TOKENIZER_MODE=jieba_sentencepiece_frozen \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL=${TOKENIZER_CONTAINER_PATH}" \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256=sha256:${TOKENIZER_SHA256}" \
    "$IMAGE" "${DIAGNOSTIC_COMMAND[@]}" >/dev/null
}

start_uat_http() {
  docker run --detach --name "$UAT_CONTAINER" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$CORE_NETWORK" \
    --publish "127.0.0.1:${HOST_PORT}:8088" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=${UAT_STATE_HOST},dst=${UAT_STATE_CONTAINER_PATH}" \
    --mount "type=bind,src=${PRIVATE_STATE_HOST},dst=${PRIVATE_STATE_CONTAINER_PATH},readonly" \
    --mount "type=bind,src=${WEB_STATE_HOST},dst=${WEB_STATE_CONTAINER_PATH}" \
    --mount "type=bind,src=${PRIVATE_SOCKET_DIR_HOST},dst=$(dirname -- "$PRIVATE_SOCKET_CONTAINER_PATH"),readonly" \
    --mount "type=bind,src=${WEB_SOCKET_DIR_HOST},dst=$(dirname -- "$WEB_SOCKET_CONTAINER_PATH"),readonly" \
    --mount "type=bind,src=${PUBLIC_ONTOLOGY},dst=${PUBLIC_ONTOLOGY_CONTAINER_PATH},readonly" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${UAT_LAUNCHER_HOST},dst=${UAT_LAUNCHER_CONTAINER_PATH},readonly" \
    --mount "type=bind,src=${CORPUS_ROOT_HOST},dst=${CORPUS_ROOT_IN_CONTAINER},readonly" \
    --mount "type=bind,src=${PRIVATE_MANIFEST_HOST},dst=${PRIVATE_MANIFEST_IN_CONTAINER},readonly" \
    --mount "type=bind,src=${TOKENIZER_MODEL},dst=${TOKENIZER_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    -e FORMOWL_MAIL_TOKENIZER_MODE=jieba_sentencepiece_frozen \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL=${TOKENIZER_CONTAINER_PATH}" \
    -e "FORMOWL_MAIL_SENTENCEPIECE_MODEL_SHA256=sha256:${TOKENIZER_SHA256}" \
    "$IMAGE" \
    python3 "$UAT_LAUNCHER_CONTAINER_PATH" \
      --host 0.0.0.0 \
      --port 8088 \
      --corpus-root "$CORPUS_ROOT_IN_CONTAINER" \
      --private-manifest "$PRIVATE_MANIFEST_IN_CONTAINER" \
      --bundle-cache "${UAT_STATE_CONTAINER_PATH}/may-bundle.private.json" \
      --state-dir "$UAT_STATE_CONTAINER_PATH" \
      --private-codex-socket "$PRIVATE_SOCKET_CONTAINER_PATH" \
      --web-codex-socket "$WEB_SOCKET_CONTAINER_PATH" \
      --private-codex-runtime-state-dir "$PRIVATE_STATE_CONTAINER_PATH" \
      --web-codex-runtime-state-dir "$WEB_STATE_CONTAINER_PATH" \
      --semantic-ontology "$PUBLIC_ONTOLOGY_CONTAINER_PATH" \
      --diagnostic-mcp-url "http://${MCP_CONTAINER}:8090/mcp" \
      --index-workers 1 >/dev/null
}

wait_for_running_container() {
  local container="$1"
  local attempt
  for attempt in $(seq 1 30); do
    [[ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" == "true" ]] &&
      return 0
    sleep 1
  done
  fail "container did not remain running: $container"
}

wait_for_socket() {
  local socket_path="$1"
  local attempt
  for attempt in $(seq 1 30); do
    [[ -S "$socket_path" ]] && return 0
    sleep 1
  done
  fail "Codex sidecar socket was not created"
}

wait_for_http_health() {
  local container="$1"
  local url="$2"
  local attempt
  for attempt in $(seq 1 30); do
    if docker exec "$container" python3 -c \
      'from urllib.request import urlopen; import sys; sys.exit(0 if urlopen(sys.argv[1], timeout=2).status == 200 else 1)' \
      "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  fail "HTTP health check did not pass: $container"
}

retain_failed_start_for_diagnostics() {
  local exit_code="$1"
  (( exit_code == 0 )) && return 0
  printf '%s\n' \
    "FORMOWL_DIAGNOSTIC_UAT_START_FAILED containers_retained_for_status_and_logs" \
    >&2
}

start() {
  local container
  for container in "$MCP_CONTAINER" "$PRIVATE_CODEX_CONTAINER" "$WEB_CODEX_CONTAINER" "$UAT_CONTAINER"; do
    assert_container_absent "$container"
  done
  prepare_runtime_paths
  ensure_network
  trap 'retain_failed_start_for_diagnostics "$?"' EXIT

  init_sidecar_state "private-planner" "$PRIVATE_STATE_HOST" "$PRIVATE_STATE_CONTAINER_PATH"
  init_sidecar_state "public-web-grounder" "$WEB_STATE_HOST" "$WEB_STATE_CONTAINER_PATH"
  start_sidecar \
    "$PRIVATE_CODEX_CONTAINER" \
    "$PRIVATE_CODEX_NETWORK" \
    "private-planner" \
    "$PRIVATE_STATE_HOST" \
    "$PRIVATE_STATE_CONTAINER_PATH" \
    "$PRIVATE_SOCKET_DIR_HOST" \
    "$PRIVATE_SOCKET_CONTAINER_PATH"
  start_sidecar \
    "$WEB_CODEX_CONTAINER" \
    "$WEB_CODEX_NETWORK" \
    "public-web-grounder" \
    "$WEB_STATE_HOST" \
    "$WEB_STATE_CONTAINER_PATH" \
    "$WEB_SOCKET_DIR_HOST" \
    "$WEB_SOCKET_CONTAINER_PATH"
  start_diagnostic_mcp
  start_uat_http

  wait_for_running_container "$PRIVATE_CODEX_CONTAINER"
  wait_for_running_container "$WEB_CODEX_CONTAINER"
  wait_for_running_container "$MCP_CONTAINER"
  wait_for_running_container "$UAT_CONTAINER"
  wait_for_socket "$PRIVATE_SOCKET_DIR_HOST/private.sock"
  wait_for_socket "$WEB_SOCKET_DIR_HOST/web.sock"
  wait_for_http_health "$MCP_CONTAINER" "http://127.0.0.1:8090/health"
  wait_for_http_health "$UAT_CONTAINER" "http://127.0.0.1:8088/"
  trap - EXIT

  printf '%s\n' "FORMOWL_DIAGNOSTIC_UAT_READY url=http://127.0.0.1:${HOST_PORT}"
  printf '%s\n' "scope=internal_diagnostic_only"
}

stop() {
  local container
  for container in "$UAT_CONTAINER" "$WEB_CODEX_CONTAINER" "$PRIVATE_CODEX_CONTAINER" "$MCP_CONTAINER"; do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  printf '%s\n' "FORMOWL_DIAGNOSTIC_UAT_STOPPED"
}

status() {
  local container
  for container in "$MCP_CONTAINER" "$PRIVATE_CODEX_CONTAINER" "$WEB_CODEX_CONTAINER" "$UAT_CONTAINER"; do
    if docker inspect -f '{{.Name}} {{.State.Status}}' "$container" 2>/dev/null; then
      :
    else
      printf '%s\n' "${container} absent"
    fi
  done
}

parse_args() {
  (($# > 0)) || {
    usage
    exit 2
  }
  ACTION="$1"
  shift
  case "$ACTION" in
    dry-run|start|status|stop) ;;
    --help|-h|help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
  while (($# > 0)); do
    case "$1" in
      --image) IMAGE="${2-}"; shift 2 ;;
      --private-root) PRIVATE_ROOT="${2-}"; shift 2 ;;
      --bridge-root) BRIDGE_ROOT="${2-}"; shift 2 ;;
      --worktree-root) WORKTREE_ROOT="${2-}"; shift 2 ;;
      --runtime-tools-root) RUNTIME_TOOLS_ROOT="${2-}"; shift 2 ;;
      --auth-cache) AUTH_CACHE="${2-}"; shift 2 ;;
      --runtime-root) RUNTIME_ROOT="${2-}"; shift 2 ;;
      --diagnostic-command-json) DIAGNOSTIC_COMMAND_JSON="${2-}"; shift 2 ;;
      --corpus-root-host) CORPUS_ROOT_HOST="${2-}"; shift 2 ;;
      --private-manifest-host) PRIVATE_MANIFEST_HOST="${2-}"; shift 2 ;;
      --tokenizer-model) TOKENIZER_MODEL="${2-}"; shift 2 ;;
      --tokenizer-sha256) TOKENIZER_SHA256="${2-}"; shift 2 ;;
      --public-ontology) PUBLIC_ONTOLOGY="${2-}"; shift 2 ;;
      --codex-command) CODEX_COMMAND="${2-}"; shift 2 ;;
      --host-port) HOST_PORT="${2-}"; shift 2 ;;
      --mcp-host-port) MCP_HOST_PORT="${2-}"; shift 2 ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        fail "unknown argument: $1"
        ;;
    esac
  done
}

main() {
  parse_args "$@"
  case "$ACTION" in
    status)
      status
      ;;
    stop)
      stop
      ;;
    dry-run)
      validate_configuration
      print_dry_run
      ;;
    start)
      validate_configuration
      start
      ;;
  esac
}

main "$@"
