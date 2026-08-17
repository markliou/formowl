#!/usr/bin/env bash
# INTERNAL DOCUMENT-FIRST UAT ONLY.
#
# This launcher intentionally starts exactly three containers:
#   1. one read-only FormOwl document MCP over the existing export,
#   2. one Codex app-server sidecar, and
#   3. one browser-facing UAT HTTP surface.
#
# The browser-facing process reaches Codex through one private Unix socket.
# Codex reaches exactly one read-only MCP through the UAT process.  This launch
# path does not provision ontology, public search, a second Codex runtime, or a
# PST parser.  It does not build images, mutate services, or claim production
# readiness.
set -Eeuo pipefail
IFS=$'\n\t'

PLAN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ACTION=""
IMAGE=""
PRIVATE_ROOT=""
BRIDGE_ROOT=""
WORKTREE_ROOT=""
AUTH_CACHE=""
RUNTIME_ROOT=""
DOCUMENT_MCP_COMMAND_JSON=""
CODEX_COMMAND="codex"
HOST_PORT="8088"
MCP_HOST_PORT="8091"
WEB_BIND_ADDRESS="127.0.0.1"

CORE_NETWORK="formowl-document-uat"
CODEX_NETWORK="formowl-document-uat-codex"
MCP_CONTAINER="formowl-document-mcp-uat"
CODEX_CONTAINER="formowl-uat-codex-sidecar"
UAT_CONTAINER="formowl-mail-document-uat"

CODEX_STATE_CONTAINER_PATH="/formowl/runtime/codex-state"
UAT_STATE_CONTAINER_PATH="/formowl/runtime/uat-state"
CODEX_SOCKET_CONTAINER_PATH="/formowl/run/codex/app-server.sock"
WORKTREE_PYTHON_CONTAINER_PATH="/opt/formowl/python"
CODEX_ENGINE_CONTAINER_PATH="/opt/formowl/scripts/mail_human_uat_codex_engine.py"
UAT_LAUNCHER_CONTAINER_PATH="/opt/formowl/scripts/mail_human_uat.py"
FORMOWL_MAIL_INIT_CONTAINER_PATH="${WORKTREE_PYTHON_CONTAINER_PATH}/formowl_mail/__init__.py"
FORMOWL_MAIL_INIT_SHIM_HOST="${PLAN_DIR}/document-uat-formowl-mail-init.py"
MODEL_READINESS_MARKER="FORMOWL_CODEX_UAT_MODEL_READY"

CODEX_STATE_HOST=""
UAT_STATE_HOST=""
CODEX_SOCKET_DIR_HOST=""
WORKTREE_PYTHON_HOST=""
CODEX_ENGINE_HOST=""
UAT_LAUNCHER_HOST=""
RUN_UID=""
RUN_GID=""
declare -a DOCUMENT_MCP_COMMAND=()
declare -a WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS=()
declare -a UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS=()

# Mount only the document-first integration seams that can differ from the
# base UAT image. The active orchestrator does not import or instantiate the
# legacy public-search adapter.
readonly WORKTREE_PYTHON_OVERLAY_FILES=(
  "formowl_contract/__init__.py"
  "formowl_contract/structured_intent.py"
  "formowl_mail/_guards.py"
  "formowl_mail/document_uat_mcp.py"
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
  --auth-cache ABSOLUTE_FILE
  --runtime-root ABSOLUTE_DIRECTORY
  --document-mcp-command-json ABSOLUTE_FILE

Optional:
  --codex-command COMMAND                       (default: codex)
  --host-port PORT                              (default: 8088)
  --mcp-host-port PORT                          (default: 8091)
  --web-bind-address IPV4                       (default: 127.0.0.1)

The document MCP command file is an operator-private JSON array of executable
arguments beginning with
`python3 /opt/formowl/python/formowl_mail/document_uat_mcp.py`. It is mounted
into no container and must not use shell execution or an arbitrary script.
The current integration launcher must expose --document-first,
--document-mcp-url, --private-codex-socket, and
--private-codex-runtime-state-dir. A dual-Codex-only launcher fails closed.
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
  [[ -f "$value" && ! -L "$value" ]] ||
    fail "$label must be a regular non-symlink file"
}

require_directory() {
  local value="$1"
  local label="$2"
  require_absolute_path "$value" "$label"
  [[ -d "$value" && ! -L "$value" ]] ||
    fail "$label must be a directory and not a symlink"
}

require_port() {
  local value="$1"
  local label="$2"
  [[ "$value" =~ ^[0-9]+$ ]] || fail "$label must be numeric"
  (( value >= 1 && value <= 65535 )) || fail "$label is out of range"
}

require_web_bind_address() {
  python3 - "$1" <<'PY' ||
import ipaddress
import sys

try:
    address = ipaddress.ip_address(sys.argv[1])
except ValueError:
    raise SystemExit(1)
if (
    address.version != 4
    or address.is_unspecified
    or address.is_multicast
    or address.is_reserved
    or not (address.is_loopback or address.is_private)
):
    raise SystemExit(1)
PY
    fail "web bind address must be an explicit loopback or private IPv4 address"
}

require_web_bind_address_assigned() {
  local value="$1"
  local address_output
  local interface_index interface_name family cidr rest

  [[ "$value" == 127.* ]] && return 0
  command -v ip >/dev/null 2>&1 ||
    fail "host IPv4 interface inspection requires ip"
  address_output="$(ip -o -4 address show)" ||
    fail "host IPv4 interface inspection failed"

  while IFS=$' \t' read -r interface_index interface_name family cidr rest; do
    if [[ "$family" == "inet" && "${cidr%%/*}" == "$value" ]]; then
      return 0
    fi
  done <<<"$address_output"

  fail "web bind address is not assigned to a host IPv4 interface: $value"
}

load_document_mcp_command() {
  require_regular_file "$DOCUMENT_MCP_COMMAND_JSON" "document MCP command JSON"
  mapfile -d '' -t DOCUMENT_MCP_COMMAND < <(
    python3 - "$DOCUMENT_MCP_COMMAND_JSON" <<'PY'
import json
from pathlib import Path
import sys

try:
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"document MCP command JSON is unreadable: {type(exc).__name__}")
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
    raise SystemExit("document MCP command JSON must be a bounded string array")
if raw[0] in {"sh", "bash", "dash", "zsh"} or "-c" in raw:
    raise SystemExit("document MCP command must not use a shell")
if (
    len(raw) < 2
    or raw[0] != "python3"
    or raw[1] != "/opt/formowl/python/formowl_mail/document_uat_mcp.py"
):
    raise SystemExit(
        "document MCP command must invoke python3 "
        "/opt/formowl/python/formowl_mail/document_uat_mcp.py"
    )
for item in raw:
    sys.stdout.buffer.write(item.encode("utf-8") + b"\0")
PY
  ) || fail "document MCP command JSON is invalid"
  (( ${#DOCUMENT_MCP_COMMAND[@]} > 0 )) || fail "document MCP command is empty"
}

detect_single_runtime_launcher_contract() {
  local option
  for option in \
    '"--document-first"' \
    '"--document-mcp-url"' \
    '"--private-codex-socket"' \
    '"--private-codex-runtime-state-dir"'; do
    grep -Fq -- "$option" "$UAT_LAUNCHER_HOST" ||
      fail "UAT launcher lacks required document-first seam: $option"
  done
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
  require_regular_file "$FORMOWL_MAIL_INIT_SHIM_HOST" "document UAT package-init shim"
  detect_single_runtime_launcher_contract
  UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS=(
    --mount
    "type=bind,src=${FORMOWL_MAIL_INIT_SHIM_HOST},dst=${FORMOWL_MAIL_INIT_CONTAINER_PATH},readonly"
  )
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

validate_configuration() {
  [[ -n "$IMAGE" ]] || fail "--image is required"
  require_directory "$PRIVATE_ROOT" "private root"
  require_directory "$BRIDGE_ROOT" "bridge root"
  validate_worktree_launchers
  require_regular_file "$AUTH_CACHE" "Codex auth cache"
  require_directory "$RUNTIME_ROOT" "runtime root"
  [[ "$CODEX_COMMAND" != *$'\n'* && "$CODEX_COMMAND" != *$'\r'* && -n "$CODEX_COMMAND" ]] ||
    fail "Codex command is invalid"
  require_port "$HOST_PORT" "host port"
  require_port "$MCP_HOST_PORT" "MCP host port"
  [[ "$HOST_PORT" != "$MCP_HOST_PORT" ]] ||
    fail "UAT and MCP host ports must differ"
  require_web_bind_address "$WEB_BIND_ADDRESS"
  require_web_bind_address_assigned "$WEB_BIND_ADDRESS"
  load_document_mcp_command
  RUN_UID="$(id -u)"
  RUN_GID="$(id -g)"
  (( RUN_UID != 0 )) || fail "the UAT launcher must run as a non-root user"
  CODEX_STATE_HOST="$RUNTIME_ROOT/codex-state"
  UAT_STATE_HOST="$RUNTIME_ROOT/uat-state"
  CODEX_SOCKET_DIR_HOST="$RUNTIME_ROOT/codex-socket"
}

print_dry_run() {
  printf '%s\n' "FORMOWL_DOCUMENT_UAT_CONFIG_VALID"
  printf '%s\n' "containers=document-mcp,codex-sidecar,uat-web"
  printf '%s\n' "codex_sidecar_count=1"
  printf '%s\n' "document_mcp_count=1"
  printf '%s\n' "document_mcp_access=read-only"
  printf '%s\n' "codex_to_mcp_route=single"
  printf '%s\n' "ontology_runtime=disabled"
  printf '%s\n' "public_search_runtime=disabled"
  printf '%s\n' "public_search_network=none"
  printf '%s\n' "second_codex_runtime=disabled"
  printf '%s\n' "pst_parser_invocation=none"
  printf '%s\n' "uat_mode=document-first"
  printf '%s\n' "uat_codex_socket_option=--private-codex-socket"
  printf '%s\n' "uat_document_mcp_option=--document-mcp-url"
  printf '%s\n' "uat_mail_bundle=disabled"
  printf '%s\n' "uat_upload=disabled"
  printf '%s\n' "model_readiness_probe=authenticated_model_only_no_mcp"
  printf '%s\n' "model_readiness_state_validation=readonly_no_metadata_mutation"
  printf '%s\n' "model_readiness_proxy_state=ephemeral_tmpfs"
  printf '%s\n' "worktree_python_overlay_count=${#WORKTREE_PYTHON_OVERLAY_FILES[@]}"
  printf '%s\n' "document_mcp_overlay=formowl_mail/document_uat_mcp.py"
  printf '%s\n' "document_mcp_guard_overlay=formowl_mail/_guards.py"
  printf '%s\n' "formowl_mail_package_init=recovery-no-eager-import-shim"
  printf '%s\n' "document_mcp_entrypoint=/opt/formowl/python/formowl_mail/document_uat_mcp.py"
  printf '%s\n' "document_mcp_command_arguments=${#DOCUMENT_MCP_COMMAND[@]}"
  printf '%s\n' "web_publish_bind_address=${WEB_BIND_ADDRESS}"
  printf '%s\n' "web_publish_endpoint=${WEB_BIND_ADDRESS}:${HOST_PORT}"
  printf '%s\n' "document_mcp_publish_bind_address=127.0.0.1"
  printf '%s\n' "document_mcp_publish_endpoint=127.0.0.1:${MCP_HOST_PORT}"
  printf '%s\n' "codex_publish=none"
  printf '%s\n' "cdp_publish=none"
}

prepare_runtime_paths() {
  local path
  for path in "$CODEX_STATE_HOST" "$UAT_STATE_HOST" "$CODEX_SOCKET_DIR_HOST"; do
    [[ ! -e "$path" ]] ||
      fail "runtime path already exists; choose a new empty --runtime-root"
  done
  for path in "$CODEX_STATE_HOST" "$UAT_STATE_HOST" "$CODEX_SOCKET_DIR_HOST"; do
    mkdir -p -- "$path"
    chmod 700 -- "$path"
  done
}

ensure_networks() {
  local network
  for network in "$CORE_NETWORK" "$CODEX_NETWORK"; do
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
  cat -- "$AUTH_CACHE" | docker run --rm -i \
    --user "${RUN_UID}:${RUN_GID}" \
    --network none \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    --mount "type=bind,src=${CODEX_STATE_HOST},dst=${CODEX_STATE_CONTAINER_PATH}" \
    "${UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS[@]}" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${CODEX_ENGINE_HOST},dst=${CODEX_ENGINE_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    "$IMAGE" \
    python3 "$CODEX_ENGINE_CONTAINER_PATH" init \
      --state-dir "$CODEX_STATE_CONTAINER_PATH" \
      --runtime-role private-planner \
      --chatgpt-auth-stdin \
      --codex-command "$CODEX_COMMAND" >/dev/null
}

start_sidecar() {
  docker run --detach --name "$CODEX_CONTAINER" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$CODEX_NETWORK" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=32m \
    --mount "type=bind,src=${CODEX_STATE_HOST},dst=${CODEX_STATE_CONTAINER_PATH}" \
    --mount "type=bind,src=${CODEX_SOCKET_DIR_HOST},dst=$(dirname -- "$CODEX_SOCKET_CONTAINER_PATH")" \
    "${UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS[@]}" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${CODEX_ENGINE_HOST},dst=${CODEX_ENGINE_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    "$IMAGE" \
    python3 "$CODEX_ENGINE_CONTAINER_PATH" serve \
      --state-dir "$CODEX_STATE_CONTAINER_PATH" \
      --runtime-role private-planner \
      --socket-path "$CODEX_SOCKET_CONTAINER_PATH" \
      --codex-command "$CODEX_COMMAND" >/dev/null
}

start_document_mcp() {
  docker run --detach --name "$MCP_CONTAINER" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$CORE_NETWORK" \
    --publish "127.0.0.1:${MCP_HOST_PORT}:8090" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=${PRIVATE_ROOT},dst=/formowl/private,readonly" \
    --mount "type=bind,src=${BRIDGE_ROOT},dst=/formowl/bridge,readonly" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    "$IMAGE" "${DOCUMENT_MCP_COMMAND[@]}" >/dev/null
}

start_uat_http() {
  local -a launcher_args=(
    --host 0.0.0.0
    --port 8088
    --document-first
    --document-mcp-url "http://${MCP_CONTAINER}:8090/mcp"
    --state-dir "$UAT_STATE_CONTAINER_PATH"
    --private-codex-socket "$CODEX_SOCKET_CONTAINER_PATH"
    --private-codex-runtime-state-dir "$CODEX_STATE_CONTAINER_PATH"
  )
  docker run --detach --name "$UAT_CONTAINER" \
    --user "${RUN_UID}:${RUN_GID}" \
    --network "$CORE_NETWORK" \
    --publish "${WEB_BIND_ADDRESS}:${HOST_PORT}:8088" \
    --read-only \
    --tmpfs /tmp:rw,noexec,nosuid,size=64m \
    --mount "type=bind,src=${UAT_STATE_HOST},dst=${UAT_STATE_CONTAINER_PATH}" \
    --mount "type=bind,src=${CODEX_STATE_HOST},dst=${CODEX_STATE_CONTAINER_PATH},readonly" \
    --mount "type=bind,src=${CODEX_SOCKET_DIR_HOST},dst=$(dirname -- "$CODEX_SOCKET_CONTAINER_PATH"),readonly" \
    "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
    --mount "type=bind,src=${UAT_LAUNCHER_HOST},dst=${UAT_LAUNCHER_CONTAINER_PATH},readonly" \
    -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
    "$IMAGE" \
    python3 "$UAT_LAUNCHER_CONTAINER_PATH" "${launcher_args[@]}" >/dev/null
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

run_model_readiness_probe() {
  local probe_output
  if ! probe_output="$(
    docker run --rm \
      --user "${RUN_UID}:${RUN_GID}" \
      --network none \
      --read-only \
      --tmpfs /tmp:rw,noexec,nosuid,size=32m \
      --mount "type=bind,src=${CODEX_STATE_HOST},dst=${CODEX_STATE_CONTAINER_PATH},readonly" \
      --mount "type=bind,src=${CODEX_SOCKET_DIR_HOST},dst=$(dirname -- "$CODEX_SOCKET_CONTAINER_PATH"),readonly" \
      "${UAT_PACKAGE_INIT_SHIM_MOUNT_ARGS[@]}" \
      "${WORKTREE_PYTHON_OVERLAY_MOUNT_ARGS[@]}" \
      --mount "type=bind,src=${CODEX_ENGINE_HOST},dst=${CODEX_ENGINE_CONTAINER_PATH},readonly" \
      -e "PYTHONPATH=${WORKTREE_PYTHON_CONTAINER_PATH}:/opt/formowl/scripts" \
      -e TMPDIR=/tmp \
      "$IMAGE" \
      python3 "$CODEX_ENGINE_CONTAINER_PATH" probe \
        --state-dir "$CODEX_STATE_CONTAINER_PATH" \
        --runtime-role private-planner \
        --socket-path "$CODEX_SOCKET_CONTAINER_PATH"
  )"; then
    fail "Codex authenticated model readiness probe failed"
  fi
  [[ "$probe_output" == "$MODEL_READINESS_MARKER" ]] ||
    fail "Codex authenticated model readiness probe returned an invalid response"
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
  stop >/dev/null 2>&1 || true
  printf '%s\n' \
    "FORMOWL_DOCUMENT_UAT_START_FAILED rollback=completed" \
    >&2
}

start() {
  local container
  for container in "$MCP_CONTAINER" "$CODEX_CONTAINER" "$UAT_CONTAINER"; do
    assert_container_absent "$container"
  done
  prepare_runtime_paths
  ensure_networks
  trap 'retain_failed_start_for_diagnostics "$?"' EXIT

  init_sidecar_state
  start_sidecar

  wait_for_running_container "$CODEX_CONTAINER"
  wait_for_socket "$CODEX_SOCKET_DIR_HOST/app-server.sock"
  run_model_readiness_probe

  start_document_mcp
  start_uat_http
  wait_for_running_container "$MCP_CONTAINER"
  wait_for_running_container "$UAT_CONTAINER"
  wait_for_http_health "$MCP_CONTAINER" "http://127.0.0.1:8090/health"
  wait_for_http_health "$UAT_CONTAINER" "http://127.0.0.1:8088/"
  trap - EXIT

  printf '%s\n' "FORMOWL_DOCUMENT_UAT_READY url=http://${WEB_BIND_ADDRESS}:${HOST_PORT}"
  printf '%s\n' "scope=internal_document_first_uat_only"
}

stop() {
  local container
  for container in "$UAT_CONTAINER" "$CODEX_CONTAINER" "$MCP_CONTAINER"; do
    docker rm -f "$container" >/dev/null 2>&1 || true
  done
  printf '%s\n' "FORMOWL_DOCUMENT_UAT_STOPPED"
}

status() {
  local container
  for container in "$MCP_CONTAINER" "$CODEX_CONTAINER" "$UAT_CONTAINER"; do
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
      --auth-cache) AUTH_CACHE="${2-}"; shift 2 ;;
      --runtime-root) RUNTIME_ROOT="${2-}"; shift 2 ;;
      --document-mcp-command-json)
        DOCUMENT_MCP_COMMAND_JSON="${2-}"
        shift 2
        ;;
      --codex-command) CODEX_COMMAND="${2-}"; shift 2 ;;
      --host-port) HOST_PORT="${2-}"; shift 2 ;;
      --mcp-host-port) MCP_HOST_PORT="${2-}"; shift 2 ;;
      --web-bind-address) WEB_BIND_ADDRESS="${2-}"; shift 2 ;;
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
