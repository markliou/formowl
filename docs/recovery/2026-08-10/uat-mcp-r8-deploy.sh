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
CANARY="$PLAN_DIR/direct-mcp-canary-r8.py"
EXPECTED_CANARY_SHA256="fc10f8af7de9d71a039d109faeabbeefc75703a9045ba183b824f00e362ffa03"
OFFLINE_ACCEPTANCE_RUNNER="$PLAN_DIR/run-offline-semantic-acceptance-r8.py"
EXPECTED_OFFLINE_ACCEPTANCE_RUNNER_SHA256="464ff0386e6baf8cd276b916c73179bfa3776b5b9dce19d06d5b875b6df426a0"
EXPECTED_INSPECT_SNAPSHOT_SHA256="614227fe991d3f9361f4f00a639aff51da87dc8dfdfbbc3e45c7ac3cff75797d"
EXPECTED_REVIEWED_IMAGE_METADATA_SHA256="845a37c9322e162b0d79f61e6b8834a50402d6180e35c1250f4a5d8bbc7b2f3f"
INSPECT_SNAPSHOT="/tmp/formowl-current-uat-containers-20260809.inspect.json"
REVIEWED_IMAGE_METADATA="/tmp/formowl-readonly-reviewed-image.json"
EXPECTED_COUNT=77
EXPECTED_FINGERPRINT="sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705"
EXPECTED_SEMANTIC_REQUEST_SHA256="sha256:20f30eb32c7525b9bedaf68b358fa0140c43cc6a77f2af03cec124a5e1dc012b"
EXPECTED_MCP_SERVER="formowl"
EXPECTED_MCP_TOOL="query_effective_graph_view"
CANDIDATE_BINDING_PATH="__CANDIDATE_BINDING_PATH__"
CANDIDATE_BINDING_SHA256="__CANDIDATE_BINDING_SHA256__"
SEMANTIC_PREFLIGHT_REPORT="__SEMANTIC_PREFLIGHT_REPORT_PATH__"
CANDIDATE_UNION_RUNTIME_ADAPTER_PATH="__CANDIDATE_UNION_RUNTIME_ADAPTER_PATH__"
CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256="__CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256__"
CANDIDATE_UNION_LEDGER_MODULE_PATH="__CANDIDATE_UNION_LEDGER_MODULE_PATH__"
CANDIDATE_UNION_LEDGER_MODULE_SHA256="__CANDIDATE_UNION_LEDGER_MODULE_SHA256__"
CANDIDATE_UNION_MATERIALIZER_MODULE_PATH="__CANDIDATE_UNION_MATERIALIZER_MODULE_PATH__"
CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256="__CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256__"
CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH="__CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH__"
CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256="__CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256__"
CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH="__CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH__"
CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256="__CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256__"
CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH="__CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH__"
CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256="__CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256__"
CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH="__CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH__"
CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256="__CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256__"
CANDIDATE_UNION_ADMISSION_PATH="__CANDIDATE_UNION_ADMISSION_PATH__"
CANDIDATE_UNION_ADMISSION_SHA256="__CANDIDATE_UNION_ADMISSION_SHA256__"
CANDIDATE_UNION_PLAN_PATH="__CANDIDATE_UNION_PLAN_PATH__"
CANDIDATE_UNION_PLAN_SHA256="__CANDIDATE_UNION_PLAN_SHA256__"
CANDIDATE_UNION_HANDOFF_PATH="__CANDIDATE_UNION_HANDOFF_PATH__"
CANDIDATE_UNION_HANDOFF_SHA256="__CANDIDATE_UNION_HANDOFF_SHA256__"
CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_PATH="__CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_PATH__"
CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_SHA256="__CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_SHA256__"
CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT=""
CANDIDATE_RUNTIME_ADAPTER_TARGET="/opt/formowl/scripts/formowl_diagnostic_mcp_sharded.py"
STAGED_ADMISSION_PATH="$PLAN_DIR/.uat-mcp-r8-candidate-union-runtime-admission.private.json"
STAGED_PLAN_PATH="$PLAN_DIR/.uat-mcp-r8-candidate-union-plan.private.json"
STAGED_HANDOFF_PATH="$PLAN_DIR/.uat-mcp-r8-candidate-union-execution-handoff.private.json"
ADMISSION_TARGET="/formowl/private/candidate-union-runtime-admission.private.json"
PLAN_TARGET="/formowl/private/reviews/candidate-union-plan.private.json"
HANDOFF_TARGET="/formowl/private/candidate-union-execution-handoff.private.json"
BROWSER_BASE_URL="http://127.0.0.1:8088"
BROWSER_CONTRACT_REPORT="$PLAN_DIR/browser-contract-r8.safe.json"
BROWSER_VERIFIER="$PLAN_DIR/verify-browser-contract-r8.py"
EXPECTED_BROWSER_VERIFIER_SHA256="8650c0a7fd613efc52fb0da59a4d18ba706fc0dd9b445ed2d2a4f08f938b543c"
CANARY_REPORT="$PLAN_DIR/direct-mcp-canary.safe.json"
DEPLOY_RESULT="$PLAN_DIR/deploy-result-safe.json"
STAGED_BINDING_PATH="$PLAN_DIR/.uat-mcp-r8-reviewed-structural-bindings.private.json"
ROLLBACK_NAME="${CONTAINER}.rollback.$(date -u +%Y%m%dT%H%M%SZ)"
CANDIDATE_CREATED=0
BASELINE_RENAMED=0
STAGED_ARTIFACTS_CREATED=0
GENERATED_BUILD_CONTEXT=""
GENERATED_CONTEXT_MANIFEST_SHA256=""
GENERATED_DOCKERFILE_SHA256=""
DOCKER_MUTATION_STARTED=0
ATTEMPT_STARTED=0
DEPLOYMENT_COMPLETE=0
BASELINE_CONFIG_FINGERPRINT=""
MAIL_BEFORE=""
SIDECAR_BEFORE=""
MAIL_WAS_RUNNING=""
SIDECAR_WAS_RUNNING=""
PRESERVED_STATES_CAPTURED=0
CANDIDATE_MCP_COMMAND=(
  "python3" "$CANDIDATE_RUNTIME_ADAPTER_TARGET"
  "--host" "0.0.0.0"
  "--port" "8090"
  "--bridge-dir" "/formowl/bridge"
  "--semantic-profile" "/formowl/private/semantic-profile.private.json"
  "--scope-authority-root" "/formowl/private/scope-authority-root.bin"
  "--current-export-table-snapshot" "/formowl/private/current-export-table-snapshot.private.json"
  "--current-export-scope-manifest" "/formowl/private/current-export-scope-manifest.private.json"
  "--current-export-selection-checkpoint" "/formowl/private/current-export-selection-checkpoint.private.json"
  "--current-export-max-message-file-bytes" "67108864"
  "--current-export-snapshot-xlsx-augmentation" "/formowl/private/current-export-xlsx-augmentation.private.json"
  "--current-export-augmentation-bridge-dir" "/formowl/private/augmentation-bridge"
  "--current-export-augmentation-semantic-profile" "/formowl/private/augmentation-semantic-profile.private.json"
  "--current-export-augmentation-scope-authority-root" "/formowl/private/augmentation-scope-authority-root.bin"
  "--candidate-union-runtime-admission" "$ADMISSION_TARGET"
  "--candidate-union-plan" "$PLAN_TARGET"
  "--candidate-union-execution-handoff" "$HANDOFF_TARGET"
)

fail() { printf '%s\n' "FAIL: $*" >&2; exit 1; }
sha256_file() { sha256sum -- "$1" | awk '{print $1}'; }
require_exact_hash() {
  [[ -f "$1" && ! -L "$1" ]] || fail "required file is missing or unsafe"
  [[ "$(sha256_file "$1")" == "$2" ]] || fail "required artifact hash mismatch"
}
require_non_placeholder() { [[ "$2" != __*__ ]] || fail "$1 must be explicitly supplied"; }

derive_canonical_semantic_request_sha256() {
  python3 - "$OFFLINE_ACCEPTANCE_RUNNER" <<'PY'
import importlib.util,sys
from pathlib import Path
path=Path(sys.argv[1])
spec=importlib.util.spec_from_file_location("formowl_r8_deployment_runner",path)
if spec is None or spec.loader is None:
    raise SystemExit(2)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
arguments=getattr(module,"_SEMANTIC_ARGUMENTS",None)
commitment=getattr(module,"_canonical_commitment",None)
if not isinstance(arguments,dict) or not callable(commitment):
    raise SystemExit(2)
print(commitment(arguments))
PY
}

validate_canonical_semantic_request_binding() {
  local observed
  observed="$(derive_canonical_semantic_request_sha256)" || fail "canonical semantic request cannot be derived from the pinned offline runner"
  [[ "$observed" == "$EXPECTED_SEMANTIC_REQUEST_SHA256" ]] || fail "canonical semantic request commitment drifted from the pinned offline runner"
}

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

preserved_container_state() {
  local name="$1"
  local state
  state="$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" || return 1
  [[ "$state" == "true" || "$state" == "false" ]] || return 1
  printf '%s\n' "$state"
}

preserved_container_port_matches() {
  local name="$1"
  local port="$2"
  local host_ip="$3"
  local matches
  matches="$(docker inspect "$name" 2>/dev/null | python3 -c '
import json,sys
port,host_ip=sys.argv[1:]
item=json.load(sys.stdin)[0]
config=item.get("Config") or {}
host=item.get("HostConfig") or {}
matches=(
    port in (config.get("ExposedPorts") or {})
    and (host.get("PortBindings") or {}).get(port)==[{"HostIp":host_ip,"HostPort":port.split("/",1)[0]}]
)
print("true" if matches else "false")' "$port" "$host_ip")" || return 1
  [[ "$matches" == "true" ]]
}

preserved_configuration_matches() {
  local name="$1"
  local fingerprint="$2"
  local port="$3"
  local host_ip="$4"
  local observed
  observed="$(safe_config_fingerprint "$name")" || return 1
  [[ "$observed" == "$fingerprint" ]] && preserved_container_port_matches "$name" "$port" "$host_ip"
}

assert_preserved_container() {
  local name="$1"
  preserved_container_state "$name" >/dev/null || fail "required preserved container is absent or unsafe"
}

record_preserved_uat_states() {
  assert_preserved_container "$SIDECAR_CONTAINER"
  assert_preserved_container "$MAIL_CONTAINER"
  SIDECAR_WAS_RUNNING="$(preserved_container_state "$SIDECAR_CONTAINER")" || fail "cannot record sidecar state"
  MAIL_WAS_RUNNING="$(preserved_container_state "$MAIL_CONTAINER")" || fail "cannot record mail state"
  SIDECAR_BEFORE="$(safe_config_fingerprint "$SIDECAR_CONTAINER")" || fail "cannot record sidecar configuration"
  MAIL_BEFORE="$(safe_config_fingerprint "$MAIL_CONTAINER")" || fail "cannot record mail configuration"
  preserved_configuration_matches "$SIDECAR_CONTAINER" "$SIDECAR_BEFORE" "8787/tcp" "127.0.0.1" || fail "sidecar required port or configuration is unsafe"
  preserved_configuration_matches "$MAIL_CONTAINER" "$MAIL_BEFORE" "8088/tcp" "" || fail "mail diagnostic required port or configuration is unsafe"
  PRESERVED_STATES_CAPTURED=1
}

wait_for_preserved_container_port() {
  local name="$1"
  local port="$2"
  local attempt
  for attempt in $(seq 1 30); do
    if timeout 2s bash -c "</dev/tcp/127.0.0.1/${port}"; then
      return 0
    fi
    [[ "$attempt" -lt 30 ]] || return 1
    sleep 1
  done
}

ensure_preserved_container_running() {
  local name="$1"
  local fingerprint="$2"
  local port="$3"
  local host_ip="$4"
  local state
  state="$(preserved_container_state "$name")" || fail "preserved container state is unavailable"
  if [[ "$state" == "false" ]]; then
    docker start "$name" >/dev/null || fail "cannot start preserved UAT container"
  fi
  [[ "$(preserved_container_state "$name")" == "true" ]] || fail "preserved UAT container did not remain running"
  preserved_configuration_matches "$name" "$fingerprint" "$port" "$host_ip" || fail "preserved UAT container configuration changed"
  wait_for_preserved_container_port "$name" "${port%/tcp}" || fail "preserved UAT container did not bind its approved local port"
}

start_preserved_uat_lifecycle() {
  [[ "$PRESERVED_STATES_CAPTURED" == "1" ]] || fail "preserved UAT state was not recorded"
  ensure_preserved_container_running "$SIDECAR_CONTAINER" "$SIDECAR_BEFORE" "8787/tcp" "127.0.0.1"
  ensure_preserved_container_running "$MAIL_CONTAINER" "$MAIL_BEFORE" "8088/tcp" ""
}

restore_preserved_container_state() {
  local name="$1"
  local expected_state="$2"
  local fingerprint="$3"
  local port="$4"
  local host_ip="$5"
  local state
  state="$(preserved_container_state "$name")" || return 1
  if [[ "$state" != "$expected_state" ]]; then
    if [[ "$expected_state" == "true" ]]; then
      docker start "$name" >/dev/null || return 1
    else
      docker stop "$name" >/dev/null || return 1
    fi
  fi
  [[ "$(preserved_container_state "$name")" == "$expected_state" ]] || return 1
  preserved_configuration_matches "$name" "$fingerprint" "$port" "$host_ip"
}

restore_preserved_uat_states() {
  [[ "$PRESERVED_STATES_CAPTURED" == "1" ]] || return 0
  local restored=1
  restore_preserved_container_state "$MAIL_CONTAINER" "$MAIL_WAS_RUNNING" "$MAIL_BEFORE" "8088/tcp" "" || restored=0
  restore_preserved_container_state "$SIDECAR_CONTAINER" "$SIDECAR_WAS_RUNNING" "$SIDECAR_BEFORE" "8787/tcp" "127.0.0.1" || restored=0
  [[ "$restored" == "1" ]]
}

assert_candidate_mcp_shape() {
  local shape
  [[ -f "$STAGED_BINDING_PATH" && ! -L "$STAGED_BINDING_PATH" ]] || fail "staged candidate binding is unsafe"
  [[ -f "$STAGED_ADMISSION_PATH" && ! -L "$STAGED_ADMISSION_PATH" ]] || fail "staged candidate admission is unsafe"
  [[ -f "$STAGED_PLAN_PATH" && ! -L "$STAGED_PLAN_PATH" ]] || fail "staged candidate plan is unsafe"
  [[ -f "$STAGED_HANDOFF_PATH" && ! -L "$STAGED_HANDOFF_PATH" ]] || fail "staged candidate handoff is unsafe"
  shape="$(docker inspect "$CONTAINER" | python3 -c '
import hashlib,json,os,stat,sys
binding_path,binding_sha256,admission_path,admission_sha256,plan_path,plan_sha256,handoff_path,handoff_sha256,context_sha256,aliases_commitment=sys.argv[1:]
x=json.load(sys.stdin)[0]
c=x.get("Config",{}); h=x.get("HostConfig",{}); mounts=x.get("Mounts",[])
def file_sha256(path):
  digest=hashlib.sha256()
  with open(path,"rb") as handle:
    for block in iter(lambda: handle.read(1024*1024),b""):
      digest.update(block)
  return digest.hexdigest()
def exact_mount(target,path,expected_sha256):
  expected_path=os.path.realpath(path)
  matching=[m for m in mounts if m.get("Destination")==target]
  if len(matching)!=1:
    return False
  mount=matching[0]; source=mount.get("Source")
  try:
    return (
      mount.get("Type")=="bind"
      and mount.get("RW") is False
      and source==expected_path
      and os.path.realpath(str(source))==expected_path
      and stat.S_ISREG(os.lstat(str(source)).st_mode)
      and not os.path.islink(str(source))
      and file_sha256(str(source))==expected_sha256
    )
  except OSError:
    return False
expected_targets={
  ("/formowl/bridge",False),
  ("/formowl/private",False),
  ("/formowl/private/reviewed-structural-bindings.private.json",False),
  ("/formowl/private/candidate-union-runtime-admission.private.json",False),
  ("/formowl/private/reviews/candidate-union-plan.private.json",False),
  ("/formowl/private/candidate-union-execution-handoff.private.json",False),
}
targets={(m.get("Destination"),m.get("RW")) for m in mounts}
cmd=c.get("Cmd") or []
expected_cmd=[
  "python3",
  "/opt/formowl/scripts/formowl_diagnostic_mcp_sharded.py",
  "--host","0.0.0.0",
  "--port","8090",
  "--bridge-dir","/formowl/bridge",
  "--semantic-profile","/formowl/private/semantic-profile.private.json",
  "--scope-authority-root","/formowl/private/scope-authority-root.bin",
  "--current-export-table-snapshot","/formowl/private/current-export-table-snapshot.private.json",
  "--current-export-scope-manifest","/formowl/private/current-export-scope-manifest.private.json",
  "--current-export-selection-checkpoint","/formowl/private/current-export-selection-checkpoint.private.json",
  "--current-export-max-message-file-bytes","67108864",
  "--current-export-snapshot-xlsx-augmentation","/formowl/private/current-export-xlsx-augmentation.private.json",
  "--current-export-augmentation-bridge-dir","/formowl/private/augmentation-bridge",
  "--current-export-augmentation-semantic-profile","/formowl/private/augmentation-semantic-profile.private.json",
  "--current-export-augmentation-scope-authority-root","/formowl/private/augmentation-scope-authority-root.bin",
  "--candidate-union-runtime-admission",
  "/formowl/private/candidate-union-runtime-admission.private.json",
  "--candidate-union-runtime-admission-sha256",
  f"sha256:{admission_sha256}",
  "--candidate-union-semantic-profile-aliases-commitment",
  aliases_commitment,
  "--candidate-union-plan",
  "/formowl/private/reviews/candidate-union-plan.private.json",
  "--candidate-union-execution-handoff",
  "/formowl/private/candidate-union-execution-handoff.private.json",
]
labels=c.get("Labels") or {}
ok=(
  c.get("Image")=="formowl-may-uat:diagnostic-reviewed-v24-20260810-r8"
  and c.get("User")=="65532:65532"
  and c.get("WorkingDir")=="/opt/formowl"
  and h.get("NetworkMode")=="formowl-diagnostic-uat"
  and h.get("RestartPolicy",{}).get("Name")=="no"
  and h.get("PortBindings",{}).get("8090/tcp")==[{"HostIp":"127.0.0.1","HostPort":"8091"}]
  and len(mounts)==6
  and targets==expected_targets
  and exact_mount("/formowl/private/reviewed-structural-bindings.private.json",binding_path,binding_sha256)
  and exact_mount("/formowl/private/candidate-union-runtime-admission.private.json",admission_path,admission_sha256)
  and exact_mount("/formowl/private/reviews/candidate-union-plan.private.json",plan_path,plan_sha256)
  and exact_mount("/formowl/private/candidate-union-execution-handoff.private.json",handoff_path,handoff_sha256)
  and cmd==expected_cmd
  and labels.get("org.formowl.uat.candidate-context-sha256")==f"sha256:{context_sha256}"
  and "FORMOWL_MAIL_TOKENIZER_MODE" in {str(v).split("=",1)[0] for v in c.get("Env") or []}
)
print("true" if ok else "false")' "$STAGED_BINDING_PATH" "$CANDIDATE_BINDING_SHA256" "$STAGED_ADMISSION_PATH" "$CANDIDATE_UNION_ADMISSION_SHA256" "$STAGED_PLAN_PATH" "$CANDIDATE_UNION_PLAN_SHA256" "$STAGED_HANDOFF_PATH" "$CANDIDATE_UNION_HANDOFF_SHA256" "$GENERATED_CONTEXT_MANIFEST_SHA256" "$CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT")"
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
  [[ -f "$SEMANTIC_PREFLIGHT_REPORT" && ! -L "$SEMANTIC_PREFLIGHT_REPORT" ]] || fail "semantic preflight report is missing or unsafe"
  python3 - "$SEMANTIC_PREFLIGHT_REPORT" "$EXPECTED_COUNT" "$EXPECTED_FINGERPRINT" "$CANDIDATE_BINDING_SHA256" "$EXPECTED_SEMANTIC_REQUEST_SHA256" "$CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256" "$CANDIDATE_UNION_LEDGER_MODULE_SHA256" "$CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256" "$CANDIDATE_UNION_ADMISSION_SHA256" "$CANDIDATE_UNION_PLAN_SHA256" "$CANDIDATE_UNION_HANDOFF_SHA256" <<'PY'
import json,re,sys
p=sys.argv[1]
count=int(sys.argv[2])
(
    fingerprint,
    binding_sha256,
    semantic_request_sha256,
    adapter_sha256,
    ledger_sha256,
    materializer_sha256,
    structural_projection_sha256,
    reviewed_structural_bindings_sha256,
    current_export_table_snapshot_sha256,
    xlsx_attachment_augmentation_sha256,
    admission_sha256,
    plan_sha256,
    handoff_sha256,
)=sys.argv[3:]
with open(p,encoding="utf-8") as handle:
    report=json.load(handle)
required_validation={
    "candidate_union_admission_bound",
    "candidate_union_plan_valid",
    "candidate_union_execution_handoff_valid",
    "candidate_union_retained_lineage_valid",
    "candidate_only_claim_contract_valid",
    "deterministic_repeat_match",
    "runtime_projection_matches_handoff",
    "oracle_loaded_after_package_runtime_freeze",
    "oracle_exact_match",
    "expected_constants_match",
}
required_commitments={
    "runtime_module_sha256",
    "source_python_tree_sha256",
    "base_bridge_sha256",
    "base_profile_sha256",
    "base_authority_sha256",
    "semantic_profile_file_sha256",
    "semantic_profile_aliases_expected_commitment",
    "current_export_snapshot_sha256",
    "current_export_max_message_file_bytes_sha256",
    "current_export_scope_manifest_sha256",
    "current_export_selection_checkpoint_sha256",
    "snapshot_xlsx_augmentation_sha256",
    "augmentation_bridge_sha256",
    "augmentation_profile_sha256",
    "augmentation_authority_sha256",
    "reviewed_structural_binding_sha256",
    "candidate_union_runtime_admission_sha256",
    "candidate_union_plan_sha256",
    "candidate_union_execution_handoff_sha256",
    "candidate_union_ledger_module_sha256",
    "candidate_union_materializer_module_sha256",
    "candidate_union_structural_projection_module_sha256",
    "candidate_union_reviewed_structural_bindings_module_sha256",
    "candidate_union_current_export_table_snapshot_module_sha256",
    "candidate_union_xlsx_attachment_augmentation_module_sha256",
    "private_oracle_sha256",
}
required_execution_bindings={
    "candidate_union_execution_handoff_sha256",
    "frozen_projection_fingerprint",
    "runtime_projection_fingerprint",
    "oracle_file_sha256",
    "semantic_request_sha256",
}
required_root={
    "artifact_type",
    "status",
    "candidate_exact_report_artifact_type",
    "candidate_exact_release_decision",
    "retrieval_path",
    "claim_state",
    "canonical_kg",
    "citation_count",
    "source_count",
    "observed_distinct_projection_count",
    "observed_fingerprint",
    "oracle_intersection_count",
    "oracle_missing_count",
    "oracle_unexpected_count",
    "deterministic_repeat_match",
    "runtime_projection_matches_handoff",
    "candidate_exact_validation_status",
    "implementation_source_commitments",
    "execution_bindings",
    "candidate_disclaimed_semantics",
    "acceptance_report_sha256",
    "candidate_binding_sha256",
    "diagnostic_only",
}
required_disclaimers={
    "source_complete":False,
    "current_state":False,
    "source_precedence":False,
    "occurrence_equivalence":False,
}
sha256=re.compile(r"sha256:[0-9a-f]{64}\Z")
validation=report.get("candidate_exact_validation_status")
commitments=report.get("implementation_source_commitments")
execution_bindings=report.get("execution_bindings")
def exact_int(value, expected):
    return type(value) is int and value == expected
checks={
    "root":set(report)==required_root,
    "artifact":report.get("artifact_type")=="formowl_r8_semantic_deployment_preflight_v1",
    "status":report.get("status")=="passed",
    "candidate_artifact":report.get("candidate_exact_report_artifact_type")=="formowl_candidate_union_exact_oracle_acceptance_report_v1",
    "candidate_release":report.get("candidate_exact_release_decision")=="CANDIDATE_EXACT_AGREE",
    "count":exact_int(report.get("observed_distinct_projection_count"),count),
    "fingerprint":report.get("observed_fingerprint")==fingerprint,
    "intersection":exact_int(report.get("oracle_intersection_count"),count),
    "missing":exact_int(report.get("oracle_missing_count"),0),
    "unexpected":exact_int(report.get("oracle_unexpected_count"),0),
    "retrieval_path":report.get("retrieval_path")=="mail_authorized_structured_set",
    "claim_state":report.get("claim_state")=="CANDIDATE_MATCHES",
    "canonical_kg":report.get("canonical_kg") is False,
    "citation_count":exact_int(report.get("citation_count"),0),
    "source_count":exact_int(report.get("source_count"),0),
    "repeat":report.get("deterministic_repeat_match") is True,
    "runtime_handoff":report.get("runtime_projection_matches_handoff") is True,
    "validation":isinstance(validation,dict) and set(validation)==required_validation and all(validation.get(key) is True for key in required_validation),
    "commitments":isinstance(commitments,dict) and set(commitments)==required_commitments and all(type(value) is str and sha256.fullmatch(value) for value in commitments.values()),
    "binding":isinstance(commitments,dict) and commitments.get("reviewed_structural_binding_sha256")==f"sha256:{binding_sha256}",
    "runtime_adapter":isinstance(commitments,dict) and commitments.get("runtime_module_sha256")==f"sha256:{adapter_sha256}",
    "ledger_module":isinstance(commitments,dict) and commitments.get("candidate_union_ledger_module_sha256")==f"sha256:{ledger_sha256}",
    "materializer_module":isinstance(commitments,dict) and commitments.get("candidate_union_materializer_module_sha256")==f"sha256:{materializer_sha256}",
    "structural_projection_module":isinstance(commitments,dict) and commitments.get("candidate_union_structural_projection_module_sha256")==f"sha256:{structural_projection_sha256}",
    "reviewed_structural_bindings_module":isinstance(commitments,dict) and commitments.get("candidate_union_reviewed_structural_bindings_module_sha256")==f"sha256:{reviewed_structural_bindings_sha256}",
    "current_export_table_snapshot_module":isinstance(commitments,dict) and commitments.get("candidate_union_current_export_table_snapshot_module_sha256")==f"sha256:{current_export_table_snapshot_sha256}",
    "xlsx_attachment_augmentation_module":isinstance(commitments,dict) and commitments.get("candidate_union_xlsx_attachment_augmentation_module_sha256")==f"sha256:{xlsx_attachment_augmentation_sha256}",
    "admission":isinstance(commitments,dict) and commitments.get("candidate_union_runtime_admission_sha256")==f"sha256:{admission_sha256}",
    "plan":isinstance(commitments,dict) and commitments.get("candidate_union_plan_sha256")==f"sha256:{plan_sha256}",
    "handoff":isinstance(commitments,dict) and commitments.get("candidate_union_execution_handoff_sha256")==f"sha256:{handoff_sha256}",
    "execution_bindings":isinstance(execution_bindings,dict) and set(execution_bindings)==required_execution_bindings and all(type(value) is str and sha256.fullmatch(value) for value in execution_bindings.values()),
    "execution_handoff":isinstance(commitments,dict) and isinstance(execution_bindings,dict) and execution_bindings.get("candidate_union_execution_handoff_sha256")==commitments.get("candidate_union_execution_handoff_sha256"),
    "frozen_projection":isinstance(execution_bindings,dict) and execution_bindings.get("frozen_projection_fingerprint")==fingerprint,
    "runtime_projection":isinstance(execution_bindings,dict) and execution_bindings.get("runtime_projection_fingerprint")==fingerprint,
    "oracle_binding":isinstance(commitments,dict) and isinstance(execution_bindings,dict) and execution_bindings.get("oracle_file_sha256")==commitments.get("private_oracle_sha256"),
    "semantic_request":isinstance(execution_bindings,dict) and execution_bindings.get("semantic_request_sha256")==semantic_request_sha256,
    "acceptance_report":isinstance(report.get("acceptance_report_sha256"),str) and sha256.fullmatch(report["acceptance_report_sha256"]) is not None,
    "candidate_binding":report.get("candidate_binding_sha256")==f"sha256:{binding_sha256}",
    "disclaimers":report.get("candidate_disclaimed_semantics")==required_disclaimers,
    "diagnostic":report.get("diagnostic_only") is True,
}
if not all(checks.values()):
    raise SystemExit("semantic preflight does not satisfy the candidate exact acceptance contract")
PY
}

bind_candidate_runtime_commitments() {
  [[ -z "$CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT" ]] || return 0
  CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT="$(
    python3 - "$SEMANTIC_PREFLIGHT_REPORT" <<'PY'
import json,re,sys
with open(sys.argv[1],encoding="utf-8") as handle:
    report=json.load(handle)
commitments=report.get("implementation_source_commitments")
value=(
    commitments.get("semantic_profile_aliases_expected_commitment")
    if isinstance(commitments,dict)
    else None
)
if not isinstance(value,str) or re.fullmatch(r"sha256:[0-9a-f]{64}",value) is None:
    raise SystemExit(2)
print(value)
PY
  )" || fail "semantic profile aliases commitment is unavailable from the validated preflight"
  CANDIDATE_MCP_COMMAND=(
    "python3" "$CANDIDATE_RUNTIME_ADAPTER_TARGET"
    "--host" "0.0.0.0"
    "--port" "8090"
    "--bridge-dir" "/formowl/bridge"
    "--semantic-profile" "/formowl/private/semantic-profile.private.json"
    "--scope-authority-root" "/formowl/private/scope-authority-root.bin"
    "--current-export-table-snapshot" "/formowl/private/current-export-table-snapshot.private.json"
    "--current-export-scope-manifest" "/formowl/private/current-export-scope-manifest.private.json"
    "--current-export-selection-checkpoint" "/formowl/private/current-export-selection-checkpoint.private.json"
    "--current-export-max-message-file-bytes" "67108864"
    "--current-export-snapshot-xlsx-augmentation" "/formowl/private/current-export-xlsx-augmentation.private.json"
    "--current-export-augmentation-bridge-dir" "/formowl/private/augmentation-bridge"
    "--current-export-augmentation-semantic-profile" "/formowl/private/augmentation-semantic-profile.private.json"
    "--current-export-augmentation-scope-authority-root" "/formowl/private/augmentation-scope-authority-root.bin"
    "--candidate-union-runtime-admission" "$ADMISSION_TARGET"
    "--candidate-union-runtime-admission-sha256" "sha256:${CANDIDATE_UNION_ADMISSION_SHA256}"
    "--candidate-union-semantic-profile-aliases-commitment" "$CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT"
    "--candidate-union-plan" "$PLAN_TARGET"
    "--candidate-union-execution-handoff" "$HANDOFF_TARGET"
  )
}

validate_candidate_union_runtime_contract() {
  local label
  local path
  local sha256
  while [[ $# -gt 0 ]]; do
    label="$1"
    path="$2"
    sha256="$3"
    shift 3
    require_non_placeholder "${label}_PATH" "$path"
    require_non_placeholder "${label}_SHA256" "$sha256"
    [[ "$sha256" =~ ^[0-9a-f]{64}$ ]] || fail "${label} SHA-256 must be exact lower-case hex"
    require_exact_hash "$path" "$sha256"
  done
}

validate_final_candidate_union_runtime() {
  validate_candidate_union_runtime_contract \
    "candidate_union_runtime_adapter" "$CANDIDATE_UNION_RUNTIME_ADAPTER_PATH" "$CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256" \
    "candidate_union_ledger_module" "$CANDIDATE_UNION_LEDGER_MODULE_PATH" "$CANDIDATE_UNION_LEDGER_MODULE_SHA256" \
    "candidate_union_materializer_module" "$CANDIDATE_UNION_MATERIALIZER_MODULE_PATH" "$CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256" \
    "candidate_union_structural_projection_module" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256" \
    "candidate_union_reviewed_structural_bindings_module" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256" \
    "candidate_union_current_export_table_snapshot_module" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256" \
    "candidate_union_xlsx_attachment_augmentation_module" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256" \
    "candidate_union_admission" "$CANDIDATE_UNION_ADMISSION_PATH" "$CANDIDATE_UNION_ADMISSION_SHA256" \
    "candidate_union_plan" "$CANDIDATE_UNION_PLAN_PATH" "$CANDIDATE_UNION_PLAN_SHA256" \
    "candidate_union_execution_handoff" "$CANDIDATE_UNION_HANDOFF_PATH" "$CANDIDATE_UNION_HANDOFF_SHA256" \
    "candidate_union_snapshot_input_manifest" "$CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_PATH" "$CANDIDATE_UNION_SNAPSHOT_INPUT_MANIFEST_SHA256"
}

validate_browser_contract_inputs() {
  require_exact_hash "$BROWSER_VERIFIER" "$EXPECTED_BROWSER_VERIFIER_SHA256"
  [[ "$BROWSER_BASE_URL" == "http://127.0.0.1:8088" ]] || fail "browser base URL drifted from the approved UAT binding"
  [[ "$BROWSER_CONTRACT_REPORT" == "$PLAN_DIR/browser-contract-r8.safe.json" ]] || fail "browser report path drifted from the approved plan-local path"
  [[ ! -e "$BROWSER_CONTRACT_REPORT" || ( -f "$BROWSER_CONTRACT_REPORT" && ! -L "$BROWSER_CONTRACT_REPORT" ) ]] || fail "browser contract report path is not a safe regular file"
}

validate_browser_contract() {
  timeout 350s python3 "$BROWSER_VERIFIER" --base-url "$BROWSER_BASE_URL" --report "$BROWSER_CONTRACT_REPORT"
  [[ -f "$BROWSER_CONTRACT_REPORT" && ! -L "$BROWSER_CONTRACT_REPORT" ]] || fail "browser contract did not write its required safe report"
  python3 - "$BROWSER_CONTRACT_REPORT" "$CANARY_REPORT" "$EXPECTED_COUNT" "$EXPECTED_FINGERPRINT" "$EXPECTED_SEMANTIC_REQUEST_SHA256" "$EXPECTED_MCP_SERVER" "$EXPECTED_MCP_TOOL" <<'PY'
import json,sys
p,canary_path,count,fingerprint,semantic_request_sha256,mcp_server,mcp_tool=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4],sys.argv[5],sys.argv[6],sys.argv[7]
with open(p,encoding="utf-8") as handle:
    browser=json.load(handle)
with open(canary_path,encoding="utf-8") as handle:
    canary=json.load(handle)
checks={
 "browser_artifact":browser.get("artifact_type")=="formowl_browser_diagnostic_contract_v2",
 "browser_status":browser.get("status")=="passed",
 "route":browser.get("query_route")=="browser_to_sidecar_to_one_mcp",
 "health_engine":browser.get("conversation_engine")=="codex_app_server",
 "health_required":browser.get("formowl_mcp_required") is True,
 "health_server_count":type(browser.get("configured_mcp_server_count")) is int and browser.get("configured_mcp_server_count")==1,
 "health_tool_count":type(browser.get("configured_mcp_tool_count")) is int and browser.get("configured_mcp_tool_count")==1,
 "model_backed":browser.get("model_backed") is True,
 "server":browser.get("mcp_server")==mcp_server,
 "tool":browser.get("mcp_tool")==mcp_tool,
 "one_mcp":type(browser.get("mcp_call_count")) is int and browser.get("mcp_call_count")==1,
 "count":type(browser.get("distinct_projection_count")) is int and browser.get("distinct_projection_count")==count,
 "fingerprint":browser.get("fingerprint")==fingerprint,
 "retrieval_path":browser.get("retrieval_path")=="mail_authorized_structured_set",
 "retrieval_layer":isinstance(browser.get("retrieval_layer"),str) and bool(browser.get("retrieval_layer").strip()),
 "canonical_kg":browser.get("canonical_kg") is False,
 "source_count":type(browser.get("source_count")) is int and browser.get("source_count")==0,
 "readability":browser.get("human_readability_guards")=={"no_initial_sources":True,"no_citations":True,"no_table_wall":True,"no_raw_dump":True,"no_placeholder_or_truncation":True},
 "canary_artifact":canary.get("artifact_type")=="formowl_r8_direct_mcp_canary_v2",
 "canary_status":canary.get("status")=="passed",
 "canary_request":canary.get("semantic_request_sha256")==semantic_request_sha256,
 "canary_server":canary.get("mcp_server")==mcp_server,
 "canary_tool":canary.get("mcp_tool")==mcp_tool,
 "canary_claim":isinstance(canary.get("safe_payload_status"),dict) and canary["safe_payload_status"].get("claim_state")=="CANDIDATE_MATCHES",
 "canary_path":isinstance(canary.get("safe_payload_status"),dict) and canary["safe_payload_status"].get("retrieval_path")=="mail_authorized_structured_set",
 "canary_canonical":isinstance(canary.get("safe_payload_status"),dict) and canary["safe_payload_status"].get("canonical_kg") is False,
 "canary_citations":isinstance(canary.get("safe_payload_status"),dict) and type(canary["safe_payload_status"].get("citation_count")) is int and canary["safe_payload_status"].get("citation_count")==0,
 "canary_sources":isinstance(canary.get("safe_payload_status"),dict) and type(canary["safe_payload_status"].get("source_count")) is int and canary["safe_payload_status"].get("source_count")==0,
}
if not all(checks.values()): raise SystemExit(2)
PY
}

validate_mount_source() {
  [[ "$1" == /* && "$1" != *,* && "$1" != *$'\n'* ]] || fail "Docker bind-mount source is unsafe"
}

validate_stage_target() {
  local label="$1"
  local target="$2"
  case "$label" in
    binding) [[ "$target" == "$PLAN_DIR/.uat-mcp-r8-reviewed-structural-bindings.private.json" ]] ;;
    admission) [[ "$target" == "$PLAN_DIR/.uat-mcp-r8-candidate-union-runtime-admission.private.json" ]] ;;
    plan) [[ "$target" == "$PLAN_DIR/.uat-mcp-r8-candidate-union-plan.private.json" ]] ;;
    handoff) [[ "$target" == "$PLAN_DIR/.uat-mcp-r8-candidate-union-execution-handoff.private.json" ]] ;;
    *) return 1 ;;
  esac || fail "staged candidate ${label} path drifted from its deployment-owned target"
  validate_mount_source "$target"
  [[ ! -e "$target" || ( -f "$target" && ! -L "$target" ) ]] || fail "staged candidate ${label} target is unsafe"
}

stage_verified_candidate_artifact() {
  local label="$1"
  local source="$2"
  local expected_sha256="$3"
  local target="$4"
  validate_stage_target "$label" "$target"
  [[ -f "$source" && ! -L "$source" ]] || fail "candidate ${label} input is unsafe"
  [[ "$(sha256_file "$source")" == "$expected_sha256" ]] || fail "candidate ${label} input hash mismatch"
  local temporary_stage
  temporary_stage="$(mktemp "${target}.XXXXXX")" || fail "cannot allocate candidate ${label} staging file"
  if ! cat -- "$source" >"$temporary_stage"; then
    rm -f -- "$temporary_stage"
    fail "cannot stage verified candidate ${label}"
  fi
  chmod 600 "$temporary_stage" || {
    rm -f -- "$temporary_stage"
    fail "cannot secure staged candidate ${label}"
  }
  [[ "$(sha256_file "$temporary_stage")" == "$expected_sha256" ]] || {
    rm -f -- "$temporary_stage"
    fail "staged candidate ${label} hash mismatch"
  }
  mv -f -- "$temporary_stage" "$target" || fail "cannot atomically publish staged candidate ${label}"
  [[ -f "$target" && ! -L "$target" ]] || fail "published staged candidate ${label} is unsafe"
  [[ "$(sha256_file "$target")" == "$expected_sha256" ]] || fail "published staged candidate ${label} hash mismatch"
}

stage_verified_candidate_artifacts() {
  stage_verified_candidate_artifact "binding" "$CANDIDATE_BINDING_PATH" "$CANDIDATE_BINDING_SHA256" "$STAGED_BINDING_PATH"
  stage_verified_candidate_artifact "admission" "$CANDIDATE_UNION_ADMISSION_PATH" "$CANDIDATE_UNION_ADMISSION_SHA256" "$STAGED_ADMISSION_PATH"
  stage_verified_candidate_artifact "plan" "$CANDIDATE_UNION_PLAN_PATH" "$CANDIDATE_UNION_PLAN_SHA256" "$STAGED_PLAN_PATH"
  stage_verified_candidate_artifact "handoff" "$CANDIDATE_UNION_HANDOFF_PATH" "$CANDIDATE_UNION_HANDOFF_SHA256" "$STAGED_HANDOFF_PATH"
  STAGED_ARTIFACTS_CREATED=1
}

generate_candidate_union_build_context() {
  local generated
  bind_candidate_runtime_commitments
  generated="$(mktemp -d "$PLAN_DIR/.uat-mcp-r8-candidate-union-build.XXXXXX")" || fail "cannot allocate candidate-union build context"
  chmod 700 "$generated" || fail "cannot secure candidate-union build context"
  mkdir "$generated/scripts" || fail "cannot allocate candidate-union runtime source directory"
  cp -- "$CANDIDATE_UNION_RUNTIME_ADAPTER_PATH" "$generated/scripts/formowl_diagnostic_mcp_sharded.py" || fail "cannot stage candidate-union runtime adapter"
  cp -- "$CANDIDATE_UNION_LEDGER_MODULE_PATH" "$generated/scripts/r8_source_only_ledgers.py" || fail "cannot stage candidate-union ledger module"
  cp -- "$CANDIDATE_UNION_MATERIALIZER_MODULE_PATH" "$generated/scripts/formowl_materialize_reviewed_bindings_private.py" || fail "cannot stage candidate-union materializer module"
  cp -- "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH" "$generated/scripts/diagnostic_structural_projection.py" || fail "cannot stage candidate-union structural projection module"
  cp -- "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH" "$generated/scripts/reviewed_structural_bindings.py" || fail "cannot stage candidate-union reviewed structural bindings module"
  cp -- "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH" "$generated/scripts/diagnostic_current_export_table_snapshot.py" || fail "cannot stage candidate-union current export table snapshot module"
  cp -- "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH" "$generated/scripts/diagnostic_xlsx_attachment_augmentation.py" || fail "cannot stage candidate-union XLSX attachment augmentation module"
  chmod 644 \
    "$generated/scripts/formowl_diagnostic_mcp_sharded.py" \
    "$generated/scripts/r8_source_only_ledgers.py" \
    "$generated/scripts/formowl_materialize_reviewed_bindings_private.py" \
    "$generated/scripts/diagnostic_structural_projection.py" \
    "$generated/scripts/reviewed_structural_bindings.py" \
    "$generated/scripts/diagnostic_current_export_table_snapshot.py" \
    "$generated/scripts/diagnostic_xlsx_attachment_augmentation.py" \
    || fail "cannot secure candidate-union runtime source modules"
  python3 - "$generated/SOURCE.sha256" "$CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256" "$CANDIDATE_UNION_LEDGER_MODULE_SHA256" "$CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256" <<'PY'
import json,sys
(
    path,
    adapter,
    ledger,
    materializer,
    structural_projection,
    reviewed_structural_bindings,
    current_export_table_snapshot,
    xlsx_attachment_augmentation,
)=sys.argv[1:]
payload={
    "artifact_id":"formowl_uat_mcp_r8_candidate_union_build_context_v1",
    "candidate_union_current_export_table_snapshot_module_sha256":f"sha256:{current_export_table_snapshot}",
    "candidate_union_ledger_module_sha256":f"sha256:{ledger}",
    "candidate_union_materializer_module_sha256":f"sha256:{materializer}",
    "candidate_union_reviewed_structural_bindings_module_sha256":f"sha256:{reviewed_structural_bindings}",
    "candidate_union_runtime_adapter_sha256":f"sha256:{adapter}",
    "candidate_union_structural_projection_module_sha256":f"sha256:{structural_projection}",
    "candidate_union_xlsx_attachment_augmentation_module_sha256":f"sha256:{xlsx_attachment_augmentation}",
}
with open(path,"w",encoding="utf-8") as handle:
    json.dump(payload,handle,sort_keys=True,separators=(",",":"))
    handle.write("\n")
PY
  chmod 600 "$generated/SOURCE.sha256" || fail "cannot secure candidate-union context manifest"
  GENERATED_CONTEXT_MANIFEST_SHA256="$(sha256_file "$generated/SOURCE.sha256")"
  cat >"$generated/Dockerfile" <<EOF
ARG FORMOWL_DIAGNOSTIC_BASE_IMAGE
FROM \${FORMOWL_DIAGNOSTIC_BASE_IMAGE}
COPY scripts/formowl_diagnostic_mcp_sharded.py /opt/formowl/scripts/formowl_diagnostic_mcp_sharded.py
COPY scripts/r8_source_only_ledgers.py /opt/formowl/scripts/r8_source_only_ledgers.py
COPY scripts/formowl_materialize_reviewed_bindings_private.py /opt/formowl/scripts/formowl_materialize_reviewed_bindings_private.py
COPY scripts/diagnostic_structural_projection.py /opt/formowl/scripts/diagnostic_structural_projection.py
COPY scripts/reviewed_structural_bindings.py /opt/formowl/scripts/reviewed_structural_bindings.py
COPY scripts/diagnostic_current_export_table_snapshot.py /opt/formowl/scripts/diagnostic_current_export_table_snapshot.py
COPY scripts/diagnostic_xlsx_attachment_augmentation.py /opt/formowl/scripts/diagnostic_xlsx_attachment_augmentation.py
LABEL org.formowl.uat.candidate-context-sha256="sha256:${GENERATED_CONTEXT_MANIFEST_SHA256}"
CMD ["python3","${CANDIDATE_RUNTIME_ADAPTER_TARGET}","--host","0.0.0.0","--port","8090","--bridge-dir","/formowl/bridge","--semantic-profile","/formowl/private/semantic-profile.private.json","--scope-authority-root","/formowl/private/scope-authority-root.bin","--current-export-table-snapshot","/formowl/private/current-export-table-snapshot.private.json","--current-export-scope-manifest","/formowl/private/current-export-scope-manifest.private.json","--current-export-selection-checkpoint","/formowl/private/current-export-selection-checkpoint.private.json","--current-export-max-message-file-bytes","67108864","--current-export-snapshot-xlsx-augmentation","/formowl/private/current-export-xlsx-augmentation.private.json","--current-export-augmentation-bridge-dir","/formowl/private/augmentation-bridge","--current-export-augmentation-semantic-profile","/formowl/private/augmentation-semantic-profile.private.json","--current-export-augmentation-scope-authority-root","/formowl/private/augmentation-scope-authority-root.bin","--candidate-union-runtime-admission","${ADMISSION_TARGET}","--candidate-union-runtime-admission-sha256","sha256:${CANDIDATE_UNION_ADMISSION_SHA256}","--candidate-union-semantic-profile-aliases-commitment","${CANDIDATE_UNION_SEMANTIC_PROFILE_ALIASES_COMMITMENT}","--candidate-union-plan","${PLAN_TARGET}","--candidate-union-execution-handoff","${HANDOFF_TARGET}"]
EOF
  chmod 600 "$generated/Dockerfile" || fail "cannot secure candidate-union Dockerfile"
  GENERATED_DOCKERFILE_SHA256="$(sha256_file "$generated/Dockerfile")"
  GENERATED_BUILD_CONTEXT="$generated"
}

assert_generated_candidate_union_build_context() {
  [[ "$GENERATED_BUILD_CONTEXT" == "$PLAN_DIR"/.uat-mcp-r8-candidate-union-build.* ]] || fail "generated candidate-union build context is unsafe"
  [[ "$GENERATED_CONTEXT_MANIFEST_SHA256" =~ ^[0-9a-f]{64}$ && "$GENERATED_DOCKERFILE_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "generated candidate-union context hashes are invalid"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/SOURCE.sha256" "$GENERATED_CONTEXT_MANIFEST_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/Dockerfile" "$GENERATED_DOCKERFILE_SHA256"
  python3 - "$GENERATED_BUILD_CONTEXT/SOURCE.sha256" "$GENERATED_BUILD_CONTEXT/Dockerfile" "$CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256" "$CANDIDATE_UNION_LEDGER_MODULE_SHA256" "$CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256" <<'PY'
import json,sys
(
    manifest_path,
    dockerfile_path,
    adapter,
    ledger,
    materializer,
    structural_projection,
    reviewed_structural_bindings,
    current_export_table_snapshot,
    xlsx_attachment_augmentation,
)=sys.argv[1:]
with open(manifest_path,encoding="utf-8") as handle:
    payload=json.load(handle)
expected_payload={
    "artifact_id":"formowl_uat_mcp_r8_candidate_union_build_context_v1",
    "candidate_union_current_export_table_snapshot_module_sha256":f"sha256:{current_export_table_snapshot}",
    "candidate_union_ledger_module_sha256":f"sha256:{ledger}",
    "candidate_union_materializer_module_sha256":f"sha256:{materializer}",
    "candidate_union_reviewed_structural_bindings_module_sha256":f"sha256:{reviewed_structural_bindings}",
    "candidate_union_runtime_adapter_sha256":f"sha256:{adapter}",
    "candidate_union_structural_projection_module_sha256":f"sha256:{structural_projection}",
    "candidate_union_xlsx_attachment_augmentation_module_sha256":f"sha256:{xlsx_attachment_augmentation}",
}
with open(dockerfile_path,encoding="utf-8") as handle:
    copy_lines=[line for line in handle.read().splitlines() if line.startswith("COPY ")]
expected_copy_lines=[
    "COPY scripts/formowl_diagnostic_mcp_sharded.py /opt/formowl/scripts/formowl_diagnostic_mcp_sharded.py",
    "COPY scripts/r8_source_only_ledgers.py /opt/formowl/scripts/r8_source_only_ledgers.py",
    "COPY scripts/formowl_materialize_reviewed_bindings_private.py /opt/formowl/scripts/formowl_materialize_reviewed_bindings_private.py",
    "COPY scripts/diagnostic_structural_projection.py /opt/formowl/scripts/diagnostic_structural_projection.py",
    "COPY scripts/reviewed_structural_bindings.py /opt/formowl/scripts/reviewed_structural_bindings.py",
    "COPY scripts/diagnostic_current_export_table_snapshot.py /opt/formowl/scripts/diagnostic_current_export_table_snapshot.py",
    "COPY scripts/diagnostic_xlsx_attachment_augmentation.py /opt/formowl/scripts/diagnostic_xlsx_attachment_augmentation.py",
]
if payload != expected_payload or copy_lines != expected_copy_lines:
    raise SystemExit("generated candidate-union context manifest or Dockerfile is incomplete")
PY
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/formowl_diagnostic_mcp_sharded.py" "$CANDIDATE_UNION_RUNTIME_ADAPTER_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/r8_source_only_ledgers.py" "$CANDIDATE_UNION_LEDGER_MODULE_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/formowl_materialize_reviewed_bindings_private.py" "$CANDIDATE_UNION_MATERIALIZER_MODULE_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/diagnostic_structural_projection.py" "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/reviewed_structural_bindings.py" "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/diagnostic_current_export_table_snapshot.py" "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_SHA256"
  require_exact_hash "$GENERATED_BUILD_CONTEXT/scripts/diagnostic_xlsx_attachment_augmentation.py" "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_SHA256"
}

validate_direct_canary_contract() {
  [[ -f "$CANARY_REPORT" && ! -L "$CANARY_REPORT" ]] || fail "direct MCP canary did not write a safe report"
  python3 - "$CANARY" "$CANARY_REPORT" "$EXPECTED_COUNT" "$EXPECTED_FINGERPRINT" "$EXPECTED_SEMANTIC_REQUEST_SHA256" "$EXPECTED_MCP_SERVER" "$EXPECTED_MCP_TOOL" <<'PY'
import ast,json,re,sys
canary_path,report_path,count,fingerprint,semantic_request_sha256,mcp_server,mcp_tool=sys.argv[1],sys.argv[2],int(sys.argv[3]),sys.argv[4],sys.argv[5],sys.argv[6],sys.argv[7]
source=open(canary_path,encoding="utf-8").read()
tree=ast.parse(source,filename=canary_path)
literals=[node.value for node in ast.walk(tree) if isinstance(node,ast.Constant) and isinstance(node.value,str)]
urlopen_calls=sum(
    isinstance(node,ast.Call)
    and isinstance(node.func,ast.Attribute)
    and node.func.attr=="urlopen"
    for node in ast.walk(tree)
)
with open(report_path,encoding="utf-8") as handle:
    report=json.load(handle)
required_root={
    "artifact_type",
    "status",
    "semantic_request_sha256",
    "mcp_server",
    "mcp_tool",
    "observed_distinct_projection_count",
    "observed_fingerprint",
    "checks",
    "safe_payload_status",
}
required_checks={
    "semantic_request_commitment",
    "status_ok",
    "candidate_claim",
    "structured_set_path",
    "authorized_execution",
    "complete_projection",
    "empty_citation_handles",
    "no_source_or_citation_payload_fields",
    "not_canonical_kg",
    "count_match",
    "fingerprint_match",
}
required_payload_status={
    "status",
    "error_code",
    "claim_state",
    "retrieval_path",
    "retrieval_layer",
    "execution_mode",
    "complete_projection_state",
    "citation_count",
    "canonical_kg",
    "source_count",
    "payload_keys",
}
required_payload_keys={
    "status",
    "claim_state",
    "retrieval_path",
    "execution_mode",
    "complete_projection",
    "citation_handles",
    "canonical_kg",
}
def source_or_citation_key(value):
    expanded=re.sub(r"(?<=[a-z0-9])(?=[A-Z])","_",value)
    tokens={token for token in re.split(r"[^0-9A-Za-z]+",expanded.casefold()) if token}
    return bool(tokens.intersection({"source","sources","citation","citations"}))
checks=report.get("checks")
safe=report.get("safe_payload_status")
valid=(
    set(report)==required_root
    and report.get("artifact_type")=="formowl_r8_direct_mcp_canary_v2"
    and report.get("status")=="passed"
    and report.get("semantic_request_sha256")==semantic_request_sha256
    and report.get("mcp_server")==mcp_server
    and report.get("mcp_tool")==mcp_tool
    and type(report.get("observed_distinct_projection_count")) is int
    and report.get("observed_distinct_projection_count")==count
    and report.get("observed_fingerprint")==fingerprint
    and isinstance(checks,dict)
    and set(checks)==required_checks
    and all(checks.get(key) is True for key in required_checks)
    and isinstance(safe,dict)
    and set(safe)==required_payload_status
    and safe.get("status")=="ok"
    and safe.get("error_code") is None
    and safe.get("claim_state")=="CANDIDATE_MATCHES"
    and safe.get("retrieval_path")=="mail_authorized_structured_set"
    and isinstance(safe.get("retrieval_layer"),str)
    and bool(safe.get("retrieval_layer").strip())
    and safe.get("execution_mode")=="authorized_structured_set"
    and safe.get("complete_projection_state")=="complete"
    and type(safe.get("citation_count")) is int
    and safe.get("citation_count")==0
    and safe.get("canonical_kg") is False
    and type(safe.get("source_count")) is int
    and safe.get("source_count")==0
    and isinstance(safe.get("payload_keys"),list)
    and all(type(value) is str for value in safe["payload_keys"])
    and required_payload_keys.issubset(set(safe["payload_keys"]))
    and all(
      key=="citation_handles" or not source_or_citation_key(key)
      for key in safe["payload_keys"]
    )
    and literals.count("tools/call")==1
    and urlopen_calls==1
)
if not valid:
    raise SystemExit("direct MCP canary does not satisfy the exact one-tools-call response contract")
PY
}

run_direct_canary_gate() {
  [[ ! -e "$CANARY_REPORT" || ( -f "$CANARY_REPORT" && ! -L "$CANARY_REPORT" ) ]] || fail "direct MCP canary report path is unsafe"
  timeout 350s python3 "$CANARY" --port "$HOST_PORT" --expected-semantic-request-sha256 "$EXPECTED_SEMANTIC_REQUEST_SHA256" >"$CANARY_REPORT"
  validate_direct_canary_contract
}

write_deployment_state() {
  local status="$1"
  local reason="$2"
  local image_id="${3:-}"
  local rollback_name="${4:-}"
  local temporary_result
  [[ "$DEPLOY_RESULT" == "$PLAN_DIR/deploy-result-safe.json" ]] || return 1
  [[ "$status" == "in_progress" || "$status" == "passed" || "$status" == "failed" || "$status" == "rollback_failed" ]] || return 1
  [[ ! -e "$DEPLOY_RESULT" || ( -f "$DEPLOY_RESULT" && ! -L "$DEPLOY_RESULT" ) ]] || return 1
  temporary_result="$(mktemp "$PLAN_DIR/.deploy-result-safe.XXXXXX")" || return 1
  if ! python3 - "$temporary_result" "$status" "$reason" "$image_id" "$rollback_name" <<'PY'
import json,sys
out,status,reason,image_id,rollback_name=sys.argv[1:]
payload={
    "status":status,
    "reason":reason,
    "candidate_container":"formowl-mcp-uat",
    "candidate_image_id":image_id or None,
    "preserved_rollback_container":rollback_name or None,
    "diagnostic_only":True,
}
with open(out,"w",encoding="utf-8") as handle:
    json.dump(payload,handle,sort_keys=True,separators=(",",":"))
    handle.write("\n")
PY
  then
    rm -f -- "$temporary_result"
    return 1
  fi
  if ! chmod 600 "$temporary_result" || ! mv -f -- "$temporary_result" "$DEPLOY_RESULT"; then
    rm -f -- "$temporary_result"
    return 1
  fi
}

begin_deployment_attempt() {
  write_deployment_state "in_progress" "attempt_started" || fail "cannot atomically invalidate a prior deployment result"
  ATTEMPT_STARTED=1
}

cleanup_staged_candidate_artifacts() {
  [[ "$STAGED_ARTIFACTS_CREATED" == 1 ]] || return 0
  rm -f -- "$STAGED_BINDING_PATH" "$STAGED_ADMISSION_PATH" "$STAGED_PLAN_PATH" "$STAGED_HANDOFF_PATH" || return 1
  [[ ! -e "$STAGED_BINDING_PATH" && ! -L "$STAGED_BINDING_PATH" ]] || return 1
  [[ ! -e "$STAGED_ADMISSION_PATH" && ! -L "$STAGED_ADMISSION_PATH" ]] || return 1
  [[ ! -e "$STAGED_PLAN_PATH" && ! -L "$STAGED_PLAN_PATH" ]] || return 1
  [[ ! -e "$STAGED_HANDOFF_PATH" && ! -L "$STAGED_HANDOFF_PATH" ]] || return 1
  STAGED_ARTIFACTS_CREATED=0
}

verify_restored_baseline() {
  [[ "$BASELINE_RENAMED" == 1 ]] || return 0
  docker inspect "$CONTAINER" >/dev/null 2>&1 || return 1
  [[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" == "false" ]] || return 1
  [[ -n "$BASELINE_CONFIG_FINGERPRINT" ]] || return 1
  [[ "$(safe_config_fingerprint "$CONTAINER")" == "$BASELINE_CONFIG_FINGERPRINT" ]]
}

rollback_exact_baseline_state() {
  local rollback_ok=1
  local candidate_removed=1
  if [[ "$DOCKER_MUTATION_STARTED" != 1 ]]; then
    restore_preserved_uat_states || return 1
    cleanup_staged_candidate_artifacts || return 1
    return 0
  fi

  if [[ "$CANDIDATE_CREATED" == 1 ]]; then
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
      docker rm -f "$CONTAINER" >/dev/null || rollback_ok=0
    fi
    if docker inspect "$CONTAINER" >/dev/null 2>&1; then
      candidate_removed=0
      rollback_ok=0
    fi
  fi

  if [[ "$BASELINE_RENAMED" == 1 ]]; then
    if docker inspect "$ROLLBACK_NAME" >/dev/null 2>&1; then
      docker rename "$ROLLBACK_NAME" "$CONTAINER" >/dev/null || rollback_ok=0
    else
      rollback_ok=0
    fi
    verify_restored_baseline || rollback_ok=0
  fi

  restore_preserved_uat_states || rollback_ok=0

  if [[ "$candidate_removed" == 1 ]]; then
    cleanup_staged_candidate_artifacts || rollback_ok=0
  fi
  [[ "$rollback_ok" == 1 ]]
}

handle_deployment_exit() {
  local rc="$1"
  trap - EXIT INT TERM
  [[ "$ATTEMPT_STARTED" == 1 ]] || exit "$rc"
  [[ "$DEPLOYMENT_COMPLETE" == 1 ]] && exit "$rc"
  if rollback_exact_baseline_state; then
    write_deployment_state "failed" "deployment_failed_after_verified_rollback" || exit 1
  else
    write_deployment_state "rollback_failed" "deployment_failed_with_incomplete_rollback" || exit 1
  fi
  exit "$rc"
}

static_self_test() {
  local deprecated_browser_command
  local browser_shell_evaluation
  local legacy_binding_selector
  deprecated_browser_command="BROWSER_CONTRACT""_COMMAND"
  browser_shell_evaluation="bash -l""c"
  legacy_binding_selector='"--reviewed-structural'
  legacy_binding_selector+='-bindings"'
  [[ "$CANDIDATE_BINDING_PATH" == "__CANDIDATE_BINDING_PATH__" ]] || fail "static mode requires the literal binding placeholder"
  [[ "$SEMANTIC_PREFLIGHT_REPORT" == "__SEMANTIC_PREFLIGHT_REPORT_PATH__" ]] || fail "static mode requires the literal semantic-report placeholder"
  [[ "$CANDIDATE_UNION_RUNTIME_ADAPTER_PATH" == "__CANDIDATE_UNION_RUNTIME_ADAPTER_PATH__" ]] || fail "static mode requires the literal candidate-union runtime placeholder"
  [[ "$CANDIDATE_UNION_LEDGER_MODULE_PATH" == "__CANDIDATE_UNION_LEDGER_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union ledger placeholder"
  [[ "$CANDIDATE_UNION_MATERIALIZER_MODULE_PATH" == "__CANDIDATE_UNION_MATERIALIZER_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union materializer placeholder"
  [[ "$CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH" == "__CANDIDATE_UNION_STRUCTURAL_PROJECTION_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union structural projection placeholder"
  [[ "$CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH" == "__CANDIDATE_UNION_REVIEWED_STRUCTURAL_BINDINGS_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union reviewed structural bindings placeholder"
  [[ "$CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH" == "__CANDIDATE_UNION_CURRENT_EXPORT_TABLE_SNAPSHOT_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union current export table snapshot placeholder"
  [[ "$CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH" == "__CANDIDATE_UNION_XLSX_ATTACHMENT_AUGMENTATION_MODULE_PATH__" ]] || fail "static mode requires the literal candidate-union XLSX attachment augmentation placeholder"
  [[ "$EXPECTED_OFFLINE_ACCEPTANCE_RUNNER_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "offline runner hash is invalid"
  require_exact_hash "$OFFLINE_ACCEPTANCE_RUNNER" "$EXPECTED_OFFLINE_ACCEPTANCE_RUNNER_SHA256"
  validate_canonical_semantic_request_binding
  [[ "$BROWSER_BASE_URL" == "http://127.0.0.1:8088" ]] || fail "browser base URL drifted from the approved UAT binding"
  [[ "$BROWSER_CONTRACT_REPORT" == "$PLAN_DIR/browser-contract-r8.safe.json" ]] || fail "browser report path drifted from the approved plan-local path"
  [[ "$EXPECTED_COUNT" == 77 && "$EXPECTED_FINGERPRINT" == sha256:d791cfcd424910ed766f4092b51c6a9c1f1b756943935544134e626301e7c705 ]] || fail "acceptance constants drifted"
  [[ "$EXPECTED_SEMANTIC_REQUEST_SHA256" =~ ^sha256:[0-9a-f]{64}$ ]] || fail "semantic request commitment is invalid"
  [[ "$CANARY" == "$PLAN_DIR/direct-mcp-canary-r8.py" ]] || fail "direct canary path drifted from the tracked plan-local canary"
  require_exact_hash "$CANARY" "$EXPECTED_CANARY_SHA256"
  require_exact_hash "$BROWSER_VERIFIER" "$EXPECTED_BROWSER_VERIFIER_SHA256"
  grep -Fq 'formowl_r8_candidate_union_execution_handoff_v3' "$OFFLINE_ACCEPTANCE_RUNNER" || fail "offline runner is not pinned to the candidate handoff v3 contract"
  grep -Fq 'stage_verified_candidate_artifacts' "$0" || fail "missing deployment-owned candidate-artifact staging gate"
  grep -Fq 'source=${STAGED_BINDING_PATH}' "$0" || fail "candidate binding mount does not use staged source"
  grep -Fq 'source=${STAGED_ADMISSION_PATH}' "$0" || fail "candidate admission mount does not use staged source"
  grep -Fq 'source=${STAGED_PLAN_PATH}' "$0" || fail "candidate plan mount does not use staged source"
  grep -Fq 'source=${STAGED_HANDOFF_PATH}' "$0" || fail "candidate handoff mount does not use staged source"
  grep -Fq 'generate_candidate_union_build_context' "$0" || fail "missing candidate-union generated build-context gate"
  grep -Fq '/opt/formowl/scripts/formowl_diagnostic_mcp_sharded.py' "$0" || fail "missing exact candidate runtime target"
  grep -Fq 'COPY scripts/r8_source_only_ledgers.py /opt/formowl/scripts/r8_source_only_ledgers.py' "$0" || fail "missing candidate-union ledger image copy"
  grep -Fq 'COPY scripts/formowl_materialize_reviewed_bindings_private.py /opt/formowl/scripts/formowl_materialize_reviewed_bindings_private.py' "$0" || fail "missing candidate-union materializer image copy"
  grep -Fq 'COPY scripts/diagnostic_structural_projection.py /opt/formowl/scripts/diagnostic_structural_projection.py' "$0" || fail "missing candidate-union structural projection image copy"
  grep -Fq 'COPY scripts/reviewed_structural_bindings.py /opt/formowl/scripts/reviewed_structural_bindings.py' "$0" || fail "missing candidate-union reviewed structural bindings image copy"
  grep -Fq 'COPY scripts/diagnostic_current_export_table_snapshot.py /opt/formowl/scripts/diagnostic_current_export_table_snapshot.py' "$0" || fail "missing candidate-union current export table snapshot image copy"
  grep -Fq 'COPY scripts/diagnostic_xlsx_attachment_augmentation.py /opt/formowl/scripts/diagnostic_xlsx_attachment_augmentation.py' "$0" || fail "missing candidate-union XLSX attachment augmentation image copy"
  grep -Fq '"--candidate-union-runtime-admission"' "$0" || fail "missing candidate admission runtime argument"
  grep -Fq '"--candidate-union-runtime-admission-sha256"' "$0" || fail "missing candidate admission hash runtime argument"
  grep -Fq '"--candidate-union-semantic-profile-aliases-commitment"' "$0" || fail "missing candidate aliases commitment runtime argument"
  grep -Fq '"--candidate-union-plan"' "$0" || fail "missing candidate plan runtime argument"
  grep -Fq '/formowl/private/reviews/candidate-union-plan.private.json' "$0" || fail "candidate plan does not preserve reviews topology"
  grep -Fq '"--candidate-union-execution-handoff"' "$0" || fail "missing candidate handoff runtime argument"
  ! grep -Fq "$legacy_binding_selector" "$0" || fail "legacy binding-only runtime selector found"
  grep -Fq 'reviewed_structural_binding_sha256' "$0" || fail "missing execution-to-binding contract"
  grep -Fq 'candidate_union_execution_handoff_sha256' "$0" || fail "missing candidate handoff commitment gate"
  grep -Fq 'semantic_request_sha256")==semantic_request_sha256' "$0" || fail "missing fixed semantic request gate"
  grep -Fq 'validate_final_candidate_union_runtime' "$0" || fail "missing final candidate-union runtime gate"
  grep -Fq 'oracle_loaded_after_package_runtime_freeze' "$0" || fail "missing candidate runtime-freeze oracle gate"
  grep -Fq 'candidate_disclaimed_semantics' "$0" || fail "missing candidate disclaimer gate"
  grep -Fq 'oracle_intersection_count' "$0" || fail "missing offline oracle intersection gate"
  grep -Fq 'handle_deployment_exit' "$0" || fail "missing terminal rollback handler"
  grep -Fq 'validate_direct_canary_contract' "$0" || fail "missing direct canary safe-output gate"
  grep -Fq 'literals.count("tools/call")==1' "$0" || fail "missing direct one-tools-call gate"
  grep -Fq -- '--expected-semantic-request-sha256 "$EXPECTED_SEMANTIC_REQUEST_SHA256"' "$0" || fail "missing canonical semantic-request canary binding"
  grep -Fq 'formowl_browser_diagnostic_contract_v2' "$0" || fail "missing immutable browser trace contract"
  grep -Fq 'docker rename "$CONTAINER" "$ROLLBACK_NAME"' "$0" || fail "missing atomic rename protection"
  grep -Fq 'assert_candidate_mcp_shape' "$0" || fail "missing candidate configuration-parity assertion"
  grep -Fq 'docker rm -f "$CONTAINER"' "$0" || fail "missing verified candidate removal"
  grep -Fq 'timeout 350s python3 "$BROWSER_VERIFIER" --base-url "$BROWSER_BASE_URL" --report "$BROWSER_CONTRACT_REPORT"' "$0" || fail "missing fixed browser verifier gate"
  ! grep -Fq "$deprecated_browser_command" "$0" || fail "arbitrary browser command input found"
  ! grep -Fq "$browser_shell_evaluation" "$0" || fail "browser shell evaluation found"
  grep -Fq 'record_preserved_uat_states' "$0" || fail "missing preserved UAT state-recording gate"
  grep -Fq 'start_preserved_uat_lifecycle' "$0" || fail "missing preserved UAT start gate"
  grep -Fq 'restore_preserved_uat_states' "$0" || fail "missing preserved UAT rollback gate"
  grep -Fq 'wait_for_preserved_container_port' "$0" || fail "missing preserved UAT local-port gate"
  ! grep -Eq 'docker (build|create|rename|rm|restart).*(formowl-mail-diagnostic-uat|formowl-codex-uat-sidecar)' "$0" || fail "preserved-container reconfiguration found"
  printf '%s\n' '{"status":"passed","static_checks":["placeholders","acceptance_constants","candidate_exact_offline_acceptance_contract","candidate_exact_runtime_freeze_oracle_gate","candidate_exact_disclaimer_gate","candidate_exact_execution_binding_gate","candidate_exact_semantic_request_gate","offline_runner_identity","candidate_union_handoff_v3_runner","final_candidate_union_runtime_placeholder_gate","candidate_union_runtime_companion_closure","preflight_binding_identity","deployment_owned_staged_candidate_artifacts","docker_inspect_staged_candidate_artifact_integrity","generated_candidate_union_build_context","candidate_union_runtime_full_cmd","candidate_union_runtime_no_legacy_binding_selector","canonical_request_direct_canary","direct_canary_one_tools_call","immutable_browser_trace_contract","terminal_rollback_state","fixed_browser_verifier","fixed_browser_base_url","plan_local_browser_report","no_browser_shell_evaluation","atomic_rename","verified_candidate_rollback","reversible_preserved_uat_lifecycle","preserved_container_required_ports","preserved_container_no_reconfiguration"]}'
}

main() {
  if [[ "${1:-}" == "--static-self-test" ]]; then
    static_self_test
    return
  fi
  [[ $# -eq 0 ]] || fail "usage: $0 [--static-self-test]"

  # A fresh atomic in-progress record prevents stale success evidence from surviving an attempt.
  begin_deployment_attempt
  trap 'handle_deployment_exit $?' EXIT
  trap 'exit 130' INT TERM

  # Nothing below this line is reached until all offline evidence is exact and bound.
  require_non_placeholder "CANDIDATE_BINDING_PATH" "$CANDIDATE_BINDING_PATH"
  require_non_placeholder "CANDIDATE_BINDING_SHA256" "$CANDIDATE_BINDING_SHA256"
  [[ "$CANDIDATE_BINDING_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "candidate binding SHA-256 must be exact lower-case hex"
  [[ -f "$CANDIDATE_BINDING_PATH" && ! -L "$CANDIDATE_BINDING_PATH" ]] || fail "candidate binding must be a regular non-symlink file"
  [[ "$(sha256_file "$CANDIDATE_BINDING_PATH")" == "$CANDIDATE_BINDING_SHA256" ]] || fail "candidate binding hash mismatch"
  validate_browser_contract_inputs
  require_exact_hash "$OFFLINE_ACCEPTANCE_RUNNER" "$EXPECTED_OFFLINE_ACCEPTANCE_RUNNER_SHA256"
  validate_canonical_semantic_request_binding
  validate_final_candidate_union_runtime
  validate_semantic_preflight
  require_exact_hash "$CANARY" "$EXPECTED_CANARY_SHA256"
  require_exact_hash "$INSPECT_SNAPSHOT" "$EXPECTED_INSPECT_SNAPSHOT_SHA256"
  require_exact_hash "$REVIEWED_IMAGE_METADATA" "$EXPECTED_REVIEWED_IMAGE_METADATA_SHA256"
  stage_verified_candidate_artifacts
  bind_candidate_runtime_commitments
  generate_candidate_union_build_context
  assert_generated_candidate_union_build_context

  docker image inspect "$BASE_IMAGE" >/dev/null 2>&1 || fail "reviewed base image is absent"
  [[ "$(docker image inspect -f '{{.Id}}' "$BASE_IMAGE")" == "$BASE_IMAGE_ID" ]] || fail "reviewed base image ID mismatch"
  record_preserved_uat_states
  assert_baseline_mcp_shape
  BASELINE_CONFIG_FINGERPRINT="$(safe_config_fingerprint "$CONTAINER")"

  # Build is local-only: no pull and no build-network access.
  DOCKER_MUTATION_STARTED=1
  docker build --pull=false --network=none -f "$GENERATED_BUILD_CONTEXT/Dockerfile" \
    --build-arg "FORMOWL_DIAGNOSTIC_BASE_IMAGE=$BASE_IMAGE" -t "$CANDIDATE_IMAGE" "$GENERATED_BUILD_CONTEXT"
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
  validate_mount_source "${MOUNT_SOURCES[0]}"
  validate_mount_source "${MOUNT_SOURCES[1]}"

  docker rename "$CONTAINER" "$ROLLBACK_NAME"
  BASELINE_RENAMED=1

  docker create --name "$CONTAINER" --network "$NETWORK" --user 65532:65532 --workdir /opt/formowl \
    --restart no --publish "127.0.0.1:${HOST_PORT}:${CONTAINER_PORT}/tcp" \
    --mount "type=bind,source=${MOUNT_SOURCES[0]},target=/formowl/bridge,readonly" \
    --mount "type=bind,source=${MOUNT_SOURCES[1]},target=/formowl/private,readonly" \
    --mount "type=bind,source=${STAGED_BINDING_PATH},target=/formowl/private/reviewed-structural-bindings.private.json,readonly" \
    --mount "type=bind,source=${STAGED_ADMISSION_PATH},target=${ADMISSION_TARGET},readonly" \
    --mount "type=bind,source=${STAGED_PLAN_PATH},target=${PLAN_TARGET},readonly" \
    --mount "type=bind,source=${STAGED_HANDOFF_PATH},target=${HANDOFF_TARGET},readonly" \
    "$CANDIDATE_IMAGE" "${CANDIDATE_MCP_COMMAND[@]}" >/dev/null
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
  run_direct_canary_gate
  start_preserved_uat_lifecycle
  validate_browser_contract
  preserved_configuration_matches "$MAIL_CONTAINER" "$MAIL_BEFORE" "8088/tcp" "" || fail "mail diagnostic container configuration changed"
  preserved_configuration_matches "$SIDECAR_CONTAINER" "$SIDECAR_BEFORE" "8787/tcp" "127.0.0.1" || fail "sidecar configuration changed"

  write_deployment_state "passed" "candidate_running_after_all_gates" "$CANDIDATE_ID" "$ROLLBACK_NAME" || fail "cannot record terminal deployment success"
  DEPLOYMENT_COMPLETE=1
  trap - EXIT INT TERM
  chmod 600 "$CANARY_REPORT" "$DEPLOY_RESULT"
  printf '%s\n' 'PASS: MCP-only candidate is running; the previous stopped container remains available under the printed rollback name.'
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
