#!/usr/bin/env bash
# INTERNAL DIAGNOSTIC UAT ONLY. Generated from a read-only audit.
# This script is intentionally inert until all __PLACEHOLDER__ values are replaced.
# It may build and replace ONLY formowl-mcp-uat when explicitly executed.
set -Eeuo pipefail
IFS=$'\n\t'

PLAN_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONTAINER="formowl-mcp-uat"
MAIL_CONTAINER="formowl-mail-diagnostic-uat"
SIDECAR_CONTAINER="formowl-codex-uat-sidecar"
NETWORK="formowl-diagnostic-uat"
HOST_PORT="8091"
CONTAINER_PORT="8090"
BASE_IMAGE="formowl-may-uat:diagnostic-reviewed-v24-20260809-r1"
BASE_IMAGE_ID="sha256:d5a7eaab66fc61dbbdac447d9e9e98c854940bbe4c6decd9346faec5f602dcec"
CANDIDATE_IMAGE="formowl-may-uat:diagnostic-reviewed-v24-20260810-r8"
BUILD_CONTEXT="/tmp/formowl-reviewed-v24-build-context"
CANARY="/tmp/formowl-mcp-direct-canary-v17-long-timeout-20260809.py"
EXPECTED_CANARY_SHA256="da29d474561d451c6c6e06fb812f3acf251c1dce19e962f6ba5dbbab3ebf6716"
EXPECTED_CONTEXT_MANIFEST_SHA256="5eb9959ee3be1cfea292b6d1b2b329ed29dd1176ef82c139d04eefa9cda5bfa8"
EXPECTED_DOCKERFILE_SHA256="5dfd9e618eb1d94e2af25a3eda8fb89260c37cac8a3a145bb6f5a2482de1da05"
EXPECTED_INSPECT_SNAPSHOT_SHA256="614227fe991d3f9361f4f00a639aff51da87dc8dfdfbbc3e45c7ac3cff75797d"
EXPECTED_REVIEWED_IMAGE_METADATA_SHA256="845a37c9322e162b0d79f61e6b8834a50402d6180e35c1250f4a5d8bbc7b2f3f"
INSPECT_SNAPSHOT="/tmp/formowl-current-uat-containers-20260809.inspect.json"
REVIEWED_IMAGE_METADATA="/tmp/formowl-readonly-reviewed-image.json"
EXPECTED_COUNT=77
EXPECTED_FINGERPRINT="sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
CANDIDATE_BINDING_PATH="__CANDIDATE_BINDING_PATH__"
CANDIDATE_BINDING_SHA256="__CANDIDATE_BINDING_SHA256__"
SEMANTIC_PREFLIGHT_REPORT="__SEMANTIC_PREFLIGHT_REPORT_PATH__"
BROWSER_CONTRACT_COMMAND="__INDEPENDENT_BROWSER_CONTRACT_COMMAND__"
BROWSER_CONTRACT_REPORT="__BROWSER_CONTRACT_REPORT_PATH__"
ROLLBACK_NAME="${CONTAINER}.rollback.$(date -u +%Y%m%dT%H%M%SZ)"
CANDIDATE_CREATED=0
BASELINE_RENAMED=0

fail() { printf '%s\n' "FAIL: $*" >&2; exit 1; }
sha256_file() { sha256sum -- "$1" | awk '{print $1}'; }
require_exact_hash() { [[ -f "$1" ]] || fail "required file is missing"; [[ "$(sha256_file "$1")" == "$2" ]] || fail "required artifact hash mismatch"; }
require_non_placeholder() { [[ "$2" != __*__ ]] || fail "$1 must be explicitly supplied"; }

safe_config_fingerprint() {
  docker inspect "$1" | python3 -c '
import hashlib,json,sys
item=json.load(sys.stdin)[0]
def env_keys(values):
  return sorted(str(v).split("=",1)[0] for v in values or [])
def mounts(values):
  out=[]
  for value in values or []:
    out.append({"type":value.get("Type"),"target":value.get("Destination"),"rw":value.get("RW"),"source_sha256":hashlib.sha256(str(value.get("Source","")).encode()).hexdigest()})
  return sorted(out,key=lambda entry:(str(entry["target"]),str(entry["type"])))
config=item.get("Config",{}); host=item.get("HostConfig",{})
safe={"name":item.get("Name"),"id":item.get("Id"),"image":config.get("Image"),"user":config.get("User"),"workdir":config.get("WorkingDir"),"entrypoint":config.get("Entrypoint"),"cmd":config.get("Cmd"),"env_keys":env_keys(config.get("Env")),"network":host.get("NetworkMode"),"ports":host.get("PortBindings"),"restart":host.get("RestartPolicy"),"mounts":mounts(item.get("Mounts"))}
print(hashlib.sha256(json.dumps(safe,sort_keys=True,separators=(",",":")).encode()).hexdigest())'
}

assert_preserved_container() {
  local name="$1"
  docker inspect "$name" >/dev/null 2>&1 || fail "required preserved container is absent"
  [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == "true" ]] || fail "preserved container is not running"
}

assert_candidate_mcp_shape() {
  local shape
  shape="$(docker inspect "$CONTAINER" | python3 -c '
import json,sys
x=json.load(sys.stdin)[0]; c=x["Config"]; h=x["HostConfig"]; mounts=x.get("Mounts",[])
targets={(m.get("Destination"),m.get("RW")) for m in mounts}
cmd=c.get("Cmd") or []
ok=(c.get("Image")=="formowl-may-uat:diagnostic-reviewed-v24-20260810-r8" and c.get("User")=="65532:65532" and c.get("WorkingDir")=="/opt/formowl" and h.get("NetworkMode")=="formowl-diagnostic-uat" and h.get("RestartPolicy",{}).get("Name")=="no" and h.get("PortBindings",{}).get("8090/tcp")==[{"HostIp":"127.0.0.1","HostPort":"8091"}] and targets=={("/formowl/bridge",False),("/formowl/private",False),("/formowl/private/reviewed-structural-bindings.private.json",False)} and "--reviewed-structural-bindings" in cmd and "/formowl/private/reviewed-structural-bindings.private.json" in cmd and "FORMOWL_MAIL_TOKENIZER_MODE" in {str(v).split("=",1)[0] for v in c.get("Env") or []})
print("true" if ok else "false")')"
  [[ "$shape" == true ]] || fail "candidate MCP configuration is not an exact approved replacement shape"
}

assert_baseline_mcp_shape() {
  docker inspect "$CONTAINER" >/dev/null 2>&1 || fail "baseline MCP container is absent"
  [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" == "false" ]] || fail "baseline MCP must be stopped before an atomic rename swap"
  [[ "$(docker inspect -f '{{.State.OOMKilled}}' "$CONTAINER")" == "false" ]] || fail "baseline MCP has OOMKilled=true; investigate before replacement"
  local shape
  shape="$(docker inspect "$CONTAINER" | python3 -c '
import json,sys
x=json.load(sys.stdin)[0]; c=x["Config"]; h=x["HostConfig"]; mounts=x.get("Mounts",[])
ok=(c.get("User")=="65532:65532" and c.get("WorkingDir")=="/opt/formowl" and h.get("NetworkMode")=="formowl-diagnostic-uat" and h.get("RestartPolicy",{}).get("Name")=="no" and h.get("PortBindings",{}).get("8090/tcp")==[{"HostIp":"127.0.0.1","HostPort":"8091"}] and {(m.get("Destination"),m.get("RW")) for m in mounts}=={("/formowl/bridge",False),("/formowl/private",False)})
print("true" if ok else "false")')"
  [[ "$shape" == true ]] || fail "baseline MCP parity shape does not match the reviewed plan"
}

validate_semantic_preflight() {
  require_non_placeholder "SEMANTIC_PREFLIGHT_REPORT" "$SEMANTIC_PREFLIGHT_REPORT"
  [[ -f "$SEMANTIC_PREFLIGHT_REPORT" ]] || fail "semantic preflight report is missing"
  python3 - "$SEMANTIC_PREFLIGHT_REPORT" "$EXPECTED_COUNT" "$EXPECTED_FINGERPRINT" <<'PY'
import json,sys
p,count,fingerprint=sys.argv[1],int(sys.argv[2]),sys.argv[3]
d=json.load(open(p,encoding="utf-8"))
def choose(*keys):
  for key in keys:
    if key in d: return d[key]
  return None
checks={
 "status":choose("status")=="passed",
 "count":choose("observed_distinct_projection_count","distinct_projection_count")==count,
 "fingerprint":choose("observed_fingerprint","fingerprint")==fingerprint,
 "claim_state":choose("claim_state")=="CANDIDATE_MATCHES",
 "retrieval_path":choose("retrieval_path")=="mail_authorized_structured_set",
 "canonical_kg":choose("canonical_kg") is False,
 "citation_count":choose("citation_count")==0,
 "source_count":choose("source_count")==0,
}
if not all(checks.values()): raise SystemExit(2)
PY
}

validate_browser_contract() {
  require_non_placeholder "BROWSER_CONTRACT_COMMAND" "$BROWSER_CONTRACT_COMMAND"
  require_non_placeholder "BROWSER_CONTRACT_REPORT" "$BROWSER_CONTRACT_REPORT"
  rm -f -- "$BROWSER_CONTRACT_REPORT"
  timeout 350s bash -lc "$BROWSER_CONTRACT_COMMAND"
  [[ -f "$BROWSER_CONTRACT_REPORT" ]] || fail "browser contract did not write its required safe report"
  python3 - "$BROWSER_CONTRACT_REPORT" "$EXPECTED_COUNT" "$EXPECTED_FINGERPRINT" <<'PY'
import json,sys
p,count,fingerprint=sys.argv[1],int(sys.argv[2]),sys.argv[3]
d=json.load(open(p,encoding="utf-8"))
checks={
 "status":d.get("status")=="passed",
 "route":d.get("query_route")=="browser_to_sidecar_to_one_mcp",
 "one_mcp":d.get("mcp_call_count")==1,
 "count":d.get("distinct_projection_count")==count,
 "fingerprint":d.get("fingerprint")==fingerprint,
 "claim_state":d.get("claim_state")=="CANDIDATE_MATCHES",
 "retrieval_path":d.get("retrieval_path")=="mail_authorized_structured_set",
 "canonical_kg":d.get("canonical_kg") is False,
 "citation_count":d.get("citation_count")==0,
 "source_count":d.get("source_count")==0,
}
if not all(checks.values()): raise SystemExit(2)
PY
}

rollback_exact_baseline_state() {
  local rc=$?
  trap - ERR EXIT INT TERM
  if [[ "$CANDIDATE_CREATED" == 1 ]] && docker inspect "$CONTAINER" >/dev/null 2>&1; then docker rm -f "$CONTAINER" >/dev/null || true; fi
  if [[ "$BASELINE_RENAMED" == 1 ]] && docker inspect "$ROLLBACK_NAME" >/dev/null 2>&1; then docker rename "$ROLLBACK_NAME" "$CONTAINER" >/dev/null || true; fi
  exit "$rc"
}

static_self_test() {
  [[ "$CANDIDATE_BINDING_PATH" == "__CANDIDATE_BINDING_PATH__" ]] || fail "static mode requires the literal binding placeholder"
  [[ "$SEMANTIC_PREFLIGHT_REPORT" == "__SEMANTIC_PREFLIGHT_REPORT_PATH__" ]] || fail "static mode requires the literal semantic-report placeholder"
  [[ "$BROWSER_CONTRACT_COMMAND" == "__INDEPENDENT_BROWSER_CONTRACT_COMMAND__" ]] || fail "static mode requires the literal browser-command placeholder"
  [[ "$BROWSER_CONTRACT_REPORT" == "__BROWSER_CONTRACT_REPORT_PATH__" ]] || fail "static mode requires the literal browser-report placeholder"
  [[ "$EXPECTED_COUNT" == 77 && "$EXPECTED_FINGERPRINT" == sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705 ]] || fail "acceptance constants drifted"
  grep -Fq 'docker rename "$CONTAINER" "$ROLLBACK_NAME"' "$0" || fail "missing atomic rename protection"
  grep -Fq 'assert_candidate_mcp_shape' "$0" || fail "missing candidate configuration-parity assertion"
  grep -Fq 'docker rm -f "$CONTAINER"' "$0" || fail "missing automatic candidate removal"
  ! grep -Eq 'docker (stop|restart|rm).*(formowl-mail-diagnostic-uat|formowl-codex-uat-sidecar)' "$0" || fail "preserved-container mutation found"
  printf '%s\n' '{"status":"passed","static_checks":["placeholders","acceptance_constants","atomic_rename","candidate_only_rollback","preserved_container_nonmutation"]}'
}

if [[ "${1:-}" == "--static-self-test" ]]; then static_self_test; exit 0; fi
[[ $# -eq 0 ]] || fail "usage: $0 [--static-self-test]"

# Nothing below this line is reached until all offline evidence is exact and bound.
require_non_placeholder "CANDIDATE_BINDING_PATH" "$CANDIDATE_BINDING_PATH"
require_non_placeholder "CANDIDATE_BINDING_SHA256" "$CANDIDATE_BINDING_SHA256"
[[ "$CANDIDATE_BINDING_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "candidate binding SHA-256 must be exact lower-case hex"
[[ -f "$CANDIDATE_BINDING_PATH" && ! -L "$CANDIDATE_BINDING_PATH" ]] || fail "candidate binding must be a regular non-symlink file"
[[ "$(sha256_file "$CANDIDATE_BINDING_PATH")" == "$CANDIDATE_BINDING_SHA256" ]] || fail "candidate binding hash mismatch"
require_exact_hash "$CANARY" "$EXPECTED_CANARY_SHA256"
require_exact_hash "$BUILD_CONTEXT/SOURCE.sha256" "$EXPECTED_CONTEXT_MANIFEST_SHA256"
require_exact_hash "$BUILD_CONTEXT/Dockerfile.overlay" "$EXPECTED_DOCKERFILE_SHA256"
require_exact_hash "$INSPECT_SNAPSHOT" "$EXPECTED_INSPECT_SNAPSHOT_SHA256"
require_exact_hash "$REVIEWED_IMAGE_METADATA" "$EXPECTED_REVIEWED_IMAGE_METADATA_SHA256"
docker image inspect "$BASE_IMAGE" >/dev/null 2>&1 || fail "reviewed base image is absent"
[[ "$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")" == "$BASE_IMAGE_ID" ]] || fail "reviewed base image ID mismatch"
assert_preserved_container "$MAIL_CONTAINER"
assert_preserved_container "$SIDECAR_CONTAINER"
MAIL_BEFORE="$(safe_config_fingerprint "$MAIL_CONTAINER")"
SIDECAR_BEFORE="$(safe_config_fingerprint "$SIDECAR_CONTAINER")"
assert_baseline_mcp_shape
validate_semantic_preflight

# Build is local-only: no pull and no build-network access.
docker build --pull=false --network=none -f "$BUILD_CONTEXT/Dockerfile.overlay" \
  --build-arg "FORMOWL_DIAGNOSTIC_BASE_IMAGE=$BASE_IMAGE" -t "$CANDIDATE_IMAGE" "$BUILD_CONTEXT"
CANDIDATE_ID="$(docker image inspect -f '{{.Id}}' "$CANDIDATE_IMAGE")"
[[ "$CANDIDATE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "candidate image ID is invalid"

# Obtain existing bridge/private host mount sources only in-memory; never print them.
readarray -t MOUNT_SOURCES < <(docker inspect "$CONTAINER" | python3 -c '
import json,sys
x=json.load(sys.stdin)[0]
found={m.get("Destination"):m for m in x.get("Mounts",[])}
for destination in ("/formowl/bridge","/formowl/private"):
  m=found.get(destination)
  if not m or m.get("Type")!="bind" or m.get("RW") is not False: raise SystemExit(2)
  print(m["Source"])')
[[ ${#MOUNT_SOURCES[@]} -eq 2 ]] || fail "cannot safely recover required read-only mount roles"

docker rename "$CONTAINER" "$ROLLBACK_NAME"
BASELINE_RENAMED=1
trap rollback_exact_baseline_state ERR EXIT INT TERM

docker create --name "$CONTAINER" --network "$NETWORK" --user 65532:65532 --workdir /opt/formowl \
  --restart no --publish "127.0.0.1:${HOST_PORT}:${CONTAINER_PORT}/tcp" \
  --mount "type=bind,src=${MOUNT_SOURCES[0]},dst=/formowl/bridge,readonly" \
  --mount "type=bind,src=${MOUNT_SOURCES[1]},dst=/formowl/private,readonly" \
  --mount "type=bind,src=${CANDIDATE_BINDING_PATH},dst=/formowl/private/reviewed-structural-bindings.private.json,readonly" \
  "$CANDIDATE_IMAGE" >/dev/null
CANDIDATE_CREATED=1
assert_candidate_mcp_shape

docker start "$CONTAINER" >/dev/null
# Health is fail-closed without assuming an undocumented route: require running state and TCP bind.
[[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" == "true" ]] || fail "candidate MCP did not remain running"
for attempt in $(seq 1 30); do
  if timeout 2s bash -c "</dev/tcp/127.0.0.1/${HOST_PORT}"; then break; fi
  [[ "$attempt" -lt 30 ]] || fail "candidate MCP did not bind its approved local port"
  sleep 1
done
# The supplied direct canary issues exactly one tools/call request; its outer timeout is < 360 seconds.
timeout 350s python3 "$CANARY" "$HOST_PORT" 日本 >"$PLAN_DIR/direct-mcp-canary.safe.json"
validate_browser_contract
[[ "$(safe_config_fingerprint "$MAIL_CONTAINER")" == "$MAIL_BEFORE" ]] || fail "mail diagnostic container configuration changed"
[[ "$(safe_config_fingerprint "$SIDECAR_CONTAINER")" == "$SIDECAR_BEFORE" ]] || fail "sidecar configuration changed"

python3 - "$PLAN_DIR/deploy-result-safe.json" "$CANDIDATE_ID" "$ROLLBACK_NAME" <<'PY'
import json,sys
out,image_id,rollback=sys.argv[1:]
with open(out,"w",encoding="utf-8") as handle:
 json.dump({"status":"passed","candidate_image_id":image_id,"candidate_container":"formowl-mcp-uat","preserved_rollback_container":rollback,"diagnostic_only":True},handle,sort_keys=True)
 handle.write("\n")
PY
chmod 600 "$PLAN_DIR/direct-mcp-canary.safe.json" "$PLAN_DIR/deploy-result-safe.json"
trap - ERR EXIT INT TERM
printf '%s\n' 'PASS: MCP-only candidate is running; the previous stopped container remains available under the printed rollback name.'
