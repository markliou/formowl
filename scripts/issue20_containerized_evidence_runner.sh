#!/bin/sh

set -eu

umask 077

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SCRIPT_PATH=$(/usr/bin/readlink -f "$0") || {
    printf '%s\n' '{"error":"runner_script_location_invalid","status":"error"}'
    exit 64
}
case "$SCRIPT_PATH" in
    */scripts/issue20_containerized_evidence_runner.sh)
        ;;
    *)
        printf '%s\n' '{"error":"runner_script_location_invalid","status":"error"}'
        exit 64
        ;;
esac
SCRIPT_DIR=${SCRIPT_PATH%/*}
ROOT=${SCRIPT_DIR%/scripts}
RUNNER_UID=$(/usr/bin/id -u)
SCRATCH_ROOT="/tmp/formowl-issue20-containerized-evidence-runner-$RUNNER_UID"
CAMPAIGN_DIR="$SCRATCH_ROOT/campaign"
SOURCE_SNAPSHOT_ROOT="$CAMPAIGN_DIR/source-snapshot"
GIT_SNAPSHOT_ROOT="$CAMPAIGN_DIR/git-snapshot"
GIT_METADATA_ROOT="$GIT_SNAPSHOT_ROOT/.git"
REPORT_DIR="$SCRATCH_ROOT/reports"
PRIVATE_LOG_BASE="$SCRATCH_ROOT/private-logs"
TRUST_INPUT_DIR="$SCRATCH_ROOT/trust-inputs"
HANDOFF_DIR="$SCRATCH_ROOT/handoff-candidates"
CAMPAIGN_PIN="$TRUST_INPUT_DIR/campaign-source-pin.json"
OPERATOR_FAILURE_DIAGNOSTIC="$SCRATCH_ROOT/private-logs/operator-postgresql-failure-diagnostic.json"
RUNNER_FAILURE_DIAGNOSTIC="$SCRATCH_ROOT/private-logs/live-postgresql-failure-diagnostic.json"
PYTHON_BIN=/usr/local/bin/python
HOST_PYTHON_BIN=/usr/bin/python3
DOCKER_BIN=/usr/bin/docker
LIVE_POSTGRESQL_VALIDATION_PROGRAM='import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); expected = {"artifact_id", "blocker_count", "status"}; raise SystemExit(0 if set(value) == expected and isinstance(value.get("artifact_id"), str) and bool(value.get("artifact_id")) and type(value.get("blocker_count")) is int and value.get("blocker_count") == 0 and value.get("status") == "passed" else 1)'
OPERATOR_FAILURE_DIAGNOSTIC_VALIDATION_PROGRAM='import json
import os
import stat
import sys

ALLOWED_STAGES = {
    "inside_migration",
    "inside_operator_commands",
    "inside_report",
    "inside_runtime_setup",
    "inside_seed",
    "inside_verification",
    "outer_authority",
    "outer_inner_journey",
    "outer_postgresql",
    "outer_report",
    "outer_runtime_cleanup",
    "outer_runtime_setup",
    "outer_secret_set",
}
EXPECTED_KEYS = {
    "artifact_id",
    "failure_code",
    "schema_version",
    "stage",
    "status",
}


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def validate():
    path = sys.argv[1]
    expected_uid = int(sys.argv[2])
    path_stat = os.lstat(path)
    if stat.S_ISLNK(path_stat.st_mode) or os.path.realpath(path) != path:
        raise ValueError("unsafe path")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened_stat = os.fstat(descriptor)
        current_stat = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != expected_uid
            or stat.S_IMODE(opened_stat.st_mode) != 0o400
            or opened_stat.st_nlink != 1
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (path_stat.st_dev, path_stat.st_ino)
            or (opened_stat.st_dev, opened_stat.st_ino)
            != (current_stat.st_dev, current_stat.st_ino)
            or opened_stat.st_size < 2
            or opened_stat.st_size > 2048
        ):
            raise ValueError("unsafe file")
        payload = b""
        while len(payload) <= 2048:
            chunk = os.read(descriptor, 2049 - len(payload))
            if not chunk:
                break
            payload += chunk
        if len(payload) != opened_stat.st_size:
            raise ValueError("unstable file")
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique_object,
        )
        if type(value) is not dict or set(value) != EXPECTED_KEYS:
            raise ValueError("invalid schema")
        if (
            type(value["artifact_id"]) is not str
            or value["artifact_id"]
            != "formowl_connected_operator_postgres_live_journey_failure_diagnostic_v1"
            or type(value["failure_code"]) is not str
            or value["failure_code"] != "stage_failed"
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
            or type(value["stage"]) is not str
            or value["stage"] not in ALLOWED_STAGES
            or type(value["status"]) is not str
            or value["status"] != "failed"
        ):
            raise ValueError("invalid value")
        return value["stage"]
    finally:
        os.close(descriptor)


try:
    print(validate())
except Exception:
    raise SystemExit(1)
'

DOCKER_HOST=unix:///var/run/docker.sock
export DOCKER_HOST
COMPOSE_DISABLE_ENV_FILE=1
export COMPOSE_DISABLE_ENV_FILE
unset DOCKER_CONTEXT DOCKER_CLI_PLUGIN_EXTRA_DIRS BUILDX_CONFIG BUILDKIT_HOST
unset COMPOSE_FILE COMPOSE_PROFILES COMPOSE_PROJECT_NAME COMPOSE_ENV_FILES
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
unset http_proxy https_proxy all_proxy no_proxy

MODE=${1:-}

if [ "$#" -eq 2 ] && [ "$MODE" = "__inside-runner" ]; then
    if ! "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" verify-inner \
        --mode "$2" \
        --root "$ROOT" \
        --scratch-root "$SCRATCH_ROOT" \
        --source-snapshot-root "$ROOT" \
        --git-metadata-root "$GIT_METADATA_ROOT" \
        --campaign-pin "$CAMPAIGN_PIN" \
        --reports-dir "$REPORT_DIR" \
        --candidate-dir "$HANDOFF_DIR" \
        --trust-input-dir "$TRUST_INPUT_DIR" \
        --script-path "$SCRIPT_PATH" \
        --python-bin "$PYTHON_BIN" \
        --docker-bin "$DOCKER_BIN" \
        --docker-socket /var/run/docker.sock \
        --home-dir "${HOME:-/invalid}" \
        --docker-config-dir "${DOCKER_CONFIG:-/invalid}" \
        --tmp-dir "${TMPDIR:-/invalid}" \
        --private-log-dir "${FORMOWL_RUNNER_PRIVATE_LOG_DIR:-/invalid}" \
        --image-id "${FORMOWL_RUNNER_IMAGE_ID:-invalid}" \
        > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_inner_boundary_unverified","status":"error"}'
        exit 1
    fi
    AUTHORITY="$TRUST_INPUT_DIR/operator-postgresql-execution-authority.json"
    AUTHORITY_PIN="$TRUST_INPUT_DIR/operator-postgresql-execution-authority-pin.json"
    AUTHORITY_CANDIDATE="$HANDOFF_DIR/operator-postgresql-execution-authority.json"
    AUTHORITY_PIN_CANDIDATE="$HANDOFF_DIR/operator-postgresql-execution-authority-pin.json"
    INTERNAL_MODE=$2

    if [ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
        || [ -L "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
        || [ -e "$RUNNER_FAILURE_DIAGNOSTIC" ] \
        || [ -L "$RUNNER_FAILURE_DIAGNOSTIC" ]; then
        exit 1
    fi

    case "$INTERNAL_MODE" in
        operator)
            REPORT="$REPORT_DIR/operator-postgresql.json"
            VALIDATION="$REPORT_DIR/operator-postgresql-validation.json"
            if [ -e "$AUTHORITY" ] || [ -L "$AUTHORITY" ] \
                || [ -e "$AUTHORITY_PIN" ] || [ -L "$AUTHORITY_PIN" ] \
                || [ -e "$AUTHORITY_CANDIDATE" ] || [ -L "$AUTHORITY_CANDIDATE" ] \
                || [ -e "$AUTHORITY_PIN_CANDIDATE" ] \
                || [ -L "$AUTHORITY_PIN_CANDIDATE" ]; then
                exit 1
            fi
            rm -f "$REPORT" "$VALIDATION"
            if "$PYTHON_BIN" \
                "$ROOT/scripts/connected_operator_postgres_live_journey.py" \
                    --output "$REPORT" \
                    --execution-authority-output "$AUTHORITY_CANDIDATE" \
                    --execution-authority-pin-output "$AUTHORITY_PIN_CANDIDATE" \
                    --failure-diagnostic-output "$OPERATOR_FAILURE_DIAGNOSTIC"; then
                if [ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
                    || [ -L "$OPERATOR_FAILURE_DIAGNOSTIC" ]; then
                    exit 1
                fi
            else
                JOURNEY_STATUS=$?
                exit "$JOURNEY_STATUS"
            fi
            for TRUST_INPUT in "$AUTHORITY_CANDIDATE" "$AUTHORITY_PIN_CANDIDATE"
            do
                TRUST_INPUT_CANONICAL=$(/usr/bin/readlink -f "$TRUST_INPUT") || exit 1
                if [ -L "$TRUST_INPUT" ] \
                    || [ ! -f "$TRUST_INPUT" ] \
                    || [ "$TRUST_INPUT_CANONICAL" != "$TRUST_INPUT" ] \
                    || [ "$(/usr/bin/stat -c '%u' "$TRUST_INPUT")" != "$RUNNER_UID" ] \
                    || [ "$(/usr/bin/stat -c '%a' "$TRUST_INPUT")" != "400" ]; then
                    exit 1
                fi
            done
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"
            "$PYTHON_BIN" "$ROOT/scripts/connected_operator_postgres_live_journey.py" \
                --validate-report "$REPORT" \
                --trusted-execution-authority "$AUTHORITY_CANDIDATE" \
                --trusted-execution-authority-pin "$AUTHORITY_PIN_CANDIDATE" \
                --output "$VALIDATION"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION"
            ;;
        operator-layer)
            REPORT="$REPORT_DIR/operator-postgresql.json"
            VALIDATION="$REPORT_DIR/operator-postgresql-revalidation.json"
            LAYER="$REPORT_DIR/operator-cli-postgresql-external-layer.json"
            for TRUST_INPUT in "$AUTHORITY" "$AUTHORITY_PIN"
            do
                TRUST_INPUT_CANONICAL=$(/usr/bin/readlink -f "$TRUST_INPUT") || exit 1
                if [ -L "$TRUST_INPUT" ] \
                    || [ ! -f "$TRUST_INPUT" ] \
                    || [ "$TRUST_INPUT_CANONICAL" != "$TRUST_INPUT" ] \
                    || [ "$(/usr/bin/stat -c '%u' "$TRUST_INPUT")" != "$RUNNER_UID" ] \
                    || [ "$(/usr/bin/stat -c '%a' "$TRUST_INPUT")" != "400" ]; then
                    exit 1
                fi
            done
            rm -f "$VALIDATION" "$LAYER"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"
            "$PYTHON_BIN" "$ROOT/scripts/connected_operator_postgres_live_journey.py" \
                --validate-report "$REPORT" \
                --trusted-execution-authority "$AUTHORITY" \
                --trusted-execution-authority-pin "$AUTHORITY_PIN" \
                --output "$VALIDATION"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION"
            "$PYTHON_BIN" "$ROOT/scripts/oauth_mcp_harness.py" \
                --operator-cli-postgresql-report "$REPORT" \
                --operator-cli-postgresql-authority "$AUTHORITY" \
                --operator-cli-postgresql-authority-pin "$AUTHORITY_PIN" \
                --operator-attest-postgresql \
                --output "$LAYER"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$LAYER"
            ;;
        live-postgresql)
            REPORT="$REPORT_DIR/live-postgresql.json"
            VALIDATION="$REPORT_DIR/live-postgresql-validation.json"
            EXECUTION_CAPTURE="${FORMOWL_RUNNER_PRIVATE_LOG_DIR}/live-postgresql-execution-error.json"
            rm -f "$REPORT" "$VALIDATION"
            if [ -e "$EXECUTION_CAPTURE" ] || [ -L "$EXECUTION_CAPTURE" ]; then
                "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    write-runner-failure-diagnostic \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$PRIVATE_LOG_BASE" \
                    --stage live_postgresql_execution \
                    --failure-code command_failed > /dev/null 2>&1 || :
                exit 1
            fi
            if "$PYTHON_BIN" \
                "$ROOT/scripts/connected_runtime_postgres_live_e2e.py" \
                    --runner-image-id "$FORMOWL_RUNNER_IMAGE_ID" \
                    --output "$REPORT" \
                    2> "$EXECUTION_CAPTURE"; then
                if ! "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    clear-live-postgresql-execution-capture \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$FORMOWL_RUNNER_PRIVATE_LOG_DIR" \
                    > /dev/null 2>&1; then
                    "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                        write-runner-failure-diagnostic \
                        --scratch-root "$SCRATCH_ROOT" \
                        --private-log-dir "$PRIVATE_LOG_BASE" \
                        --stage live_postgresql_execution \
                        --failure-code command_failed > /dev/null 2>&1 || :
                    exit 1
                fi
            else
                FAILURE_CODE=command_failed
                if MAPPED_FAILURE_CODE=$(
                    "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                        consume-live-postgresql-execution-error \
                        --scratch-root "$SCRATCH_ROOT" \
                        --private-log-dir "$FORMOWL_RUNNER_PRIVATE_LOG_DIR" \
                        2> /dev/null
                ); then
                    case "$MAPPED_FAILURE_CODE" in
                        report_persist_failed)
                            FAILURE_CODE=$MAPPED_FAILURE_CODE
                            ;;
                    esac
                fi
                /bin/rm -f -- "$EXECUTION_CAPTURE" > /dev/null 2>&1 || :
                "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    write-runner-failure-diagnostic \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$PRIVATE_LOG_BASE" \
                    --stage live_postgresql_execution \
                    --failure-code "$FAILURE_CODE" > /dev/null 2>&1 || :
                exit 1
            fi
            if ! "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"; then
                "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    write-runner-failure-diagnostic \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$PRIVATE_LOG_BASE" \
                    --stage live_postgresql_report \
                    --failure-code report_rejected > /dev/null 2>&1 || :
                exit 1
            fi
            if ! "$PYTHON_BIN" \
                "$ROOT/scripts/connected_runtime_postgres_live_e2e.py" \
                    --output "$REPORT" \
                    --validate-report > "$VALIDATION"; then
                "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    write-runner-failure-diagnostic \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$PRIVATE_LOG_BASE" \
                    --stage live_postgresql_report_validation \
                    --failure-code command_failed > /dev/null 2>&1 || :
                exit 1
            fi
            if ! "$PYTHON_BIN" -c "$LIVE_POSTGRESQL_VALIDATION_PROGRAM" \
                "$VALIDATION"; then
                "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                    write-runner-failure-diagnostic \
                    --scratch-root "$SCRATCH_ROOT" \
                    --private-log-dir "$PRIVATE_LOG_BASE" \
                    --stage live_postgresql_validation \
                    --failure-code validation_rejected > /dev/null 2>&1 || :
                exit 1
            fi
            ;;
        lifecycle-a)
            REPORT="$REPORT_DIR/production-lifecycle-a.json"
            VALIDATION="$REPORT_DIR/production-lifecycle-a-validation.json"
            rm -f "$REPORT" "$VALIDATION"
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --output "$REPORT"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --validate-report "$REPORT" > "$VALIDATION"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION"
            ;;
        lifecycle-b)
            REPORT="$REPORT_DIR/production-lifecycle-b.json"
            VALIDATION="$REPORT_DIR/production-lifecycle-b-validation.json"
            rm -f "$REPORT" "$VALIDATION"
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --output "$REPORT"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --validate-report "$REPORT" > "$VALIDATION"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION"
            ;;
        lifecycle-aggregate)
            REPORT_A="$REPORT_DIR/production-lifecycle-a.json"
            REPORT_B="$REPORT_DIR/production-lifecycle-b.json"
            VALIDATION_A="$REPORT_DIR/production-lifecycle-a-revalidation.json"
            VALIDATION_B="$REPORT_DIR/production-lifecycle-b-revalidation.json"
            AGGREGATE="$REPORT_DIR/production-lifecycle-external-layer.json"
            rm -f "$VALIDATION_A" "$VALIDATION_B" "$AGGREGATE"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT_A"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT_B"
            HASH_A=$(/usr/bin/sha256sum "$REPORT_A")
            HASH_A=${HASH_A%% *}
            HASH_B=$(/usr/bin/sha256sum "$REPORT_B")
            HASH_B=${HASH_B%% *}
            if [ "$HASH_A" = "$HASH_B" ]; then
                exit 1
            fi
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --validate-report "$REPORT_A" > "$VALIDATION_A"
            "$PYTHON_BIN" "$ROOT/scripts/connected_runtime_container_lifecycle_probe.py" \
                --validate-report "$REPORT_B" > "$VALIDATION_B"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION_A"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION_B"
            "$PYTHON_BIN" "$ROOT/scripts/oauth_mcp_harness.py" \
                --aggregate-lifecycle-reports "$REPORT_A" "$REPORT_B" \
                --operator-attest-lifecycle \
                --output "$AGGREGATE"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$AGGREGATE"
            ;;
        local-harness)
            REPORT="$REPORT_DIR/local-oauth-harness.json"
            VALIDATION="$REPORT_DIR/local-oauth-harness-validation.json"
            rm -f "$REPORT" "$VALIDATION"
            "$PYTHON_BIN" "$ROOT/scripts/oauth_mcp_harness.py" \
                --output "$REPORT"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("status") == "passed" else 1)' \
                "$REPORT"
            "$PYTHON_BIN" "$ROOT/scripts/oauth_mcp_harness.py" \
                --validate-report "$REPORT" \
                --output "$VALIDATION"
            "$PYTHON_BIN" -c \
                'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is True else 1)' \
                "$VALIDATION"
            ;;
        *)
            exit 64
            ;;
    esac

    if /usr/bin/grep -R -F "$ROOT" "$REPORT_DIR" > /dev/null \
        || /usr/bin/grep -R -F '/var/run/docker.sock' "$REPORT_DIR" > /dev/null; then
        exit 1
    fi
    exit 0
fi

LOCKED_OUTER=0
if [ "$#" -eq 2 ] && [ "$MODE" = "__locked-outer" ]; then
    if ! "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" verify-held-lock \
        --lock-fd 9 > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_invocation_lock_unverified","status":"error"}'
        exit 1
    fi
    MODE=$2
    LOCKED_OUTER=1
elif [ "$#" -ne 1 ]; then
    printf '%s\n' '{"error":"runner_mode_required","status":"error"}'
    exit 64
fi

if [ "$MODE" = "__inside-preflight" ]; then
    if ! "$PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" verify-inner \
        --mode preflight \
        --root "$ROOT" \
        --scratch-root "$SCRATCH_ROOT" \
        --source-snapshot-root "$ROOT" \
        --git-metadata-root "$GIT_METADATA_ROOT" \
        --campaign-pin "$CAMPAIGN_PIN" \
        --reports-dir "$REPORT_DIR" \
        --candidate-dir "$HANDOFF_DIR" \
        --trust-input-dir "$TRUST_INPUT_DIR" \
        --script-path "$SCRIPT_PATH" \
        --python-bin "$PYTHON_BIN" \
        --docker-bin "$DOCKER_BIN" \
        --docker-socket /var/run/docker.sock \
        --home-dir "${HOME:-/invalid}" \
        --docker-config-dir "${DOCKER_CONFIG:-/invalid}" \
        --tmp-dir "${TMPDIR:-/invalid}" \
        --private-log-dir "${FORMOWL_RUNNER_PRIVATE_LOG_DIR:-/invalid}" \
        --image-id "${FORMOWL_RUNNER_IMAGE_ID:-invalid}" \
        > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_inner_boundary_unverified","status":"error"}'
        exit 1
    fi
    FIXTURE="$TMPDIR/nested-bind-fixture.txt"
    INVALID_REPORT="$TMPDIR/invalid-report.json"
    VALIDATION_REPORT="$TMPDIR/invalid-report-validation.json"
    PRIVATE_LOG="$FORMOWL_RUNNER_PRIVATE_LOG_DIR/preflight.log"

    trap 'rm -f "$FIXTURE" "$INVALID_REPORT" "$VALIDATION_REPORT" "$PRIVATE_LOG"' EXIT HUP INT TERM

    if ! "$DOCKER_BIN" version --format '{{.Server.Version}}' > /dev/null 2> "$PRIVATE_LOG"; then
        printf '%s\n' '{"error":"runner_docker_daemon_unavailable","status":"error"}'
        exit 1
    fi
    if ! "$DOCKER_BIN" buildx version > /dev/null 2> "$PRIVATE_LOG"; then
        printf '%s\n' '{"error":"runner_docker_buildx_unavailable","status":"error"}'
        exit 1
    fi
    if ! "$DOCKER_BIN" compose version --short > /dev/null 2> "$PRIVATE_LOG"; then
        printf '%s\n' '{"error":"runner_docker_compose_unavailable","status":"error"}'
        exit 1
    fi

    printf '%s\n' 'formowl-issue20-runner-fixture-v1' > "$FIXTURE"
    EXPECTED_HASH=$(/usr/bin/sha256sum "$FIXTURE")
    EXPECTED_HASH=${EXPECTED_HASH%% *}
    if ! NESTED_OUTPUT=$("$DOCKER_BIN" run --rm \
        --volume "$ROOT:$ROOT:ro" \
        --volume "$SCRATCH_ROOT:$SCRATCH_ROOT:ro" \
        --workdir "$ROOT" \
        "$FORMOWL_RUNNER_IMAGE_ID" \
        /usr/bin/sha256sum "$FIXTURE" 2> "$PRIVATE_LOG"); then
        printf '%s\n' '{"error":"runner_nested_bind_unavailable","status":"error"}'
        exit 1
    fi
    NESTED_HASH=${NESTED_OUTPUT%% *}
    if [ "$NESTED_HASH" != "$EXPECTED_HASH" ]; then
        printf '%s\n' '{"error":"runner_nested_bind_mismatch","status":"error"}'
        exit 1
    fi

    for SCRIPT in \
        scripts/issue20_runner_boundary.py \
        scripts/connected_operator_postgres_live_journey.py \
        scripts/connected_runtime_container_lifecycle_probe.py \
        scripts/connected_runtime_postgres_live_e2e.py \
        scripts/oauth_mcp_harness.py
    do
        if ! "$PYTHON_BIN" "$SCRIPT" --help > /dev/null 2> "$PRIVATE_LOG"; then
            printf '%s\n' '{"error":"runner_issue20_script_startup_failed","status":"error"}'
            exit 1
        fi
    done

    printf '%s\n' '{}' > "$INVALID_REPORT"
    if "$PYTHON_BIN" scripts/connected_operator_postgres_live_journey.py \
        --validate-report "$INVALID_REPORT" \
        --output "$VALIDATION_REPORT" > /dev/null 2> "$PRIVATE_LOG"; then
        printf '%s\n' '{"error":"runner_invalid_report_was_accepted","status":"error"}'
        exit 1
    fi
    if ! "$PYTHON_BIN" -c \
        'import json, sys; value = json.load(open(sys.argv[1], encoding="utf-8")); raise SystemExit(0 if value.get("passed") is False and isinstance(value.get("blockers"), list) else 1)' \
        "$VALIDATION_REPORT" > /dev/null 2> "$PRIVATE_LOG"; then
        printf '%s\n' '{"error":"runner_safe_validation_unavailable","status":"error"}'
        exit 1
    fi
    if /usr/bin/grep -F "$ROOT" "$VALIDATION_REPORT" > /dev/null \
        || /usr/bin/grep -F '/var/run/docker.sock' "$VALIDATION_REPORT" > /dev/null; then
        printf '%s\n' '{"error":"runner_validation_output_leak","status":"error"}'
        exit 1
    fi

    printf '%s\n' '{"artifact_type":"issue20_containerized_evidence_runner_preflight_v1","docker_authority":"trusted_operator_docker_daemon","docker_cli":true,"docker_compose":true,"docker_daemon":true,"host_docker_socket_delegated":true,"issue20_script_startup_count":5,"nested_workspace_bind":true,"safe_validation":true,"sandboxed_untrusted_source":false,"status":"passed"}'
    exit 0
fi

case "$MODE" in
    preflight | operator | operator-layer | live-postgresql | lifecycle-a | lifecycle-b | lifecycle-aggregate | local-harness)
        ;;
    *)
        printf '%s\n' '{"error":"runner_mode_invalid","status":"error"}'
        exit 64
        ;;
esac

if [ -L "$SCRATCH_ROOT" ]; then
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
fi
if [ -e "$SCRATCH_ROOT" ]; then
    if [ ! -d "$SCRATCH_ROOT" ] \
        || [ "$(/usr/bin/stat -c '%u' "$SCRATCH_ROOT")" != "$RUNNER_UID" ]; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
elif ! /usr/bin/mkdir -m 700 "$SCRATCH_ROOT"; then
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
fi
SCRATCH_CANONICAL=$(/usr/bin/readlink -f "$SCRATCH_ROOT") || {
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
}
if [ "$SCRATCH_CANONICAL" != "$SCRATCH_ROOT" ] \
    || ! /usr/bin/chmod 700 "$SCRATCH_ROOT" \
    || [ "$(/usr/bin/stat -c '%a' "$SCRATCH_ROOT")" != "700" ]; then
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
fi

HOME_BASE="$SCRATCH_ROOT/home"
TMP_BASE="$SCRATCH_ROOT/tmp"

for CHILD_NAME in campaign handoff-candidates home tmp reports private-logs trust-inputs
do
    CHILD_PATH="$SCRATCH_ROOT/$CHILD_NAME"
    if [ -L "$CHILD_PATH" ]; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
    if [ -e "$CHILD_PATH" ]; then
        if [ ! -d "$CHILD_PATH" ] \
            || [ "$(/usr/bin/stat -c '%u' "$CHILD_PATH")" != "$RUNNER_UID" ] \
            || [ "$(/usr/bin/stat -c '%a' "$CHILD_PATH")" != "700" ]; then
            printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
            exit 1
        fi
    elif ! /usr/bin/mkdir -m 700 "$CHILD_PATH"; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
    CHILD_CANONICAL=$(/usr/bin/readlink -f "$CHILD_PATH") || {
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    }
    if [ "$CHILD_CANONICAL" != "$CHILD_PATH" ] \
        || [ "$(/usr/bin/stat -c '%u' "$CHILD_PATH")" != "$RUNNER_UID" ] \
        || [ "$(/usr/bin/stat -c '%a' "$CHILD_PATH")" != "700" ]; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
done

if [ ! -f "$ROOT/containers/dev/Dockerfile" ] \
    || [ "$SCRIPT_PATH" != "$ROOT/scripts/issue20_containerized_evidence_runner.sh" ]; then
    printf '%s\n' '{"error":"runner_repository_root_required","status":"error"}'
    exit 64
fi
if [ "$LOCKED_OUTER" -eq 0 ]; then
    exec "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" lock-and-exec \
        --root "$ROOT" \
        --script-path "$SCRIPT_PATH" \
        --mode "$MODE" \
        2> /dev/null
fi
# The inherited abstract-socket descriptor stays bound through inner completion.
if [ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
    || [ -L "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
    || [ -e "$RUNNER_FAILURE_DIAGNOSTIC" ] \
    || [ -L "$RUNNER_FAILURE_DIAGNOSTIC" ]; then
    printf '%s\n' '{"error":"runner_command_failed","status":"error"}'
    exit 1
fi
DOCKER_RESOLVED=$(/usr/bin/readlink -f "$DOCKER_BIN") || {
    printf '%s\n' '{"error":"runner_docker_cli_untrusted","status":"error"}'
    exit 1
}
DOCKER_MODE=$(/usr/bin/stat -c '%a' "$DOCKER_RESOLVED") || {
    printf '%s\n' '{"error":"runner_docker_cli_untrusted","status":"error"}'
    exit 1
}
if [ ! -x "$DOCKER_RESOLVED" ] \
    || [ "$(/usr/bin/stat -c '%u' "$DOCKER_RESOLVED")" != "0" ] \
    || [ $((0$DOCKER_MODE & 0022)) -ne 0 ]; then
    printf '%s\n' '{"error":"runner_docker_cli_untrusted","status":"error"}'
    exit 1
fi
if [ ! -S /var/run/docker.sock ]; then
    printf '%s\n' '{"error":"runner_docker_socket_unavailable","status":"error"}'
    exit 1
fi

INVOCATION_HOME_ROOT=
INVOCATION_TMP_ROOT=
INVOCATION_LOG_ROOT=
CAMPAIGN_INITIALIZING=0
trap '[ "$CAMPAIGN_INITIALIZING" -eq 0 ] || { /bin/rm -rf -- "$SOURCE_SNAPSHOT_ROOT" "$GIT_SNAPSHOT_ROOT"; /bin/rm -f -- "$CAMPAIGN_PIN"; }; [ -z "$INVOCATION_HOME_ROOT" ] || /bin/rm -rf -- "$INVOCATION_HOME_ROOT"; [ -z "$INVOCATION_TMP_ROOT" ] || /bin/rm -rf -- "$INVOCATION_TMP_ROOT"; [ -z "$INVOCATION_LOG_ROOT" ] || /bin/rm -rf -- "$INVOCATION_LOG_ROOT"' EXIT HUP INT TERM
INVOCATION_HOME_ROOT=$(/usr/bin/mktemp -d "$HOME_BASE/invocation.XXXXXXXXXX") || {
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
}
INVOCATION_TMP_ROOT=$(/usr/bin/mktemp -d "$TMP_BASE/invocation.XXXXXXXXXX") || {
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
}
INVOCATION_LOG_ROOT=$(/usr/bin/mktemp -d "$PRIVATE_LOG_BASE/invocation.XXXXXXXXXX") || {
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
}
for FRESH_ROOT in "$INVOCATION_HOME_ROOT" "$INVOCATION_TMP_ROOT" "$INVOCATION_LOG_ROOT"
do
    FRESH_CANONICAL=$(/usr/bin/readlink -f "$FRESH_ROOT") || {
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    }
    if [ -L "$FRESH_ROOT" ] \
        || [ ! -d "$FRESH_ROOT" ] \
        || [ "$FRESH_CANONICAL" != "$FRESH_ROOT" ] \
        || [ "$(/usr/bin/stat -c '%u' "$FRESH_ROOT")" != "$RUNNER_UID" ] \
        || [ "$(/usr/bin/stat -c '%a' "$FRESH_ROOT")" != "700" ] \
        || [ -n "$(/usr/bin/find "$FRESH_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
done

OUTER_HOME="$INVOCATION_HOME_ROOT/outer-home"
OUTER_DOCKER_CONFIG="$INVOCATION_HOME_ROOT/outer-docker-config"
INNER_HOME="$INVOCATION_HOME_ROOT/inner-home"
INNER_DOCKER_CONFIG="$INVOCATION_HOME_ROOT/inner-docker-config"
OUTER_TMP="$INVOCATION_TMP_ROOT/outer-tmp"
INNER_TMP="$INVOCATION_TMP_ROOT/inner-tmp"
OUTER_LOG_DIR="$INVOCATION_LOG_ROOT/outer-logs"
INNER_LOG_DIR="$INVOCATION_LOG_ROOT/inner-logs"
if ! /usr/bin/mkdir -m 700 \
    "$OUTER_HOME" \
    "$OUTER_DOCKER_CONFIG" \
    "$INNER_HOME" \
    "$INNER_DOCKER_CONFIG" \
    "$OUTER_TMP" \
    "$INNER_TMP" \
    "$OUTER_LOG_DIR" \
    "$INNER_LOG_DIR"; then
    printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
    exit 1
fi
for FRESH_DIR in \
    "$OUTER_HOME" \
    "$OUTER_DOCKER_CONFIG" \
    "$INNER_HOME" \
    "$INNER_DOCKER_CONFIG" \
    "$OUTER_TMP" \
    "$INNER_TMP" \
    "$OUTER_LOG_DIR" \
    "$INNER_LOG_DIR"
do
    FRESH_CANONICAL=$(/usr/bin/readlink -f "$FRESH_DIR") || {
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    }
    case "$FRESH_DIR" in
        "$HOME_BASE"/* | "$TMP_BASE"/* | "$PRIVATE_LOG_BASE"/*)
            ;;
        *)
            printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
            exit 1
            ;;
    esac
    if [ -L "$FRESH_DIR" ] \
        || [ ! -d "$FRESH_DIR" ] \
        || [ "$FRESH_CANONICAL" != "$FRESH_DIR" ] \
        || [ "$(/usr/bin/stat -c '%u' "$FRESH_DIR")" != "$RUNNER_UID" ] \
        || [ "$(/usr/bin/stat -c '%a' "$FRESH_DIR")" != "700" ] \
        || [ -n "$(/usr/bin/find "$FRESH_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
        printf '%s\n' '{"error":"runner_scratch_unavailable","status":"error"}'
        exit 1
    fi
done

SNAPSHOT_LOG="$OUTER_LOG_DIR/source-snapshot.log"
GIT_SNAPSHOT_LOG="$OUTER_LOG_DIR/git-snapshot.log"
BUILD_LOG="$OUTER_LOG_DIR/build.log"
RUN_LOG="$OUTER_LOG_DIR/$MODE.log"
SNAPSHOT_DOCKERFILE="$OUTER_TMP/source-snapshot.Dockerfile"
IMAGE_ID_FILE="$OUTER_TMP/formowl-dev.iid"

if ! SOCKET_GID=$(stat -c '%g' /var/run/docker.sock 2> /dev/null); then
    printf '%s\n' '{"error":"runner_docker_socket_group_unavailable","status":"error"}'
    exit 1
fi

if [ ! -e "$CAMPAIGN_PIN" ] && [ ! -L "$CAMPAIGN_PIN" ]; then
    if [ "$MODE" != "preflight" ] \
        || [ -n "$(/usr/bin/find "$CAMPAIGN_DIR" -mindepth 1 -print -quit)" ] \
        || [ -n "$(/usr/bin/find "$TRUST_INPUT_DIR" -mindepth 1 -print -quit)" ]; then
        printf '%s\n' '{"error":"runner_campaign_required","status":"error"}'
        exit 1
    fi
    CAMPAIGN_INITIALIZING=1
    if ! /usr/bin/mkdir -m 700 "$SOURCE_SNAPSHOT_ROOT" "$GIT_SNAPSHOT_ROOT"; then
        printf '%s\n' '{"error":"runner_campaign_invalid","status":"error"}'
        exit 1
    fi
    if ! printf '%s\n' \
        'FROM scratch' \
        'ARG SNAPSHOT_UID' \
        'ARG SNAPSHOT_GID' \
        'COPY --chown=${SNAPSHOT_UID}:${SNAPSHOT_GID} . /' \
        > "$SNAPSHOT_DOCKERFILE"; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    if ! /usr/bin/env -i \
        "PATH=$PATH" \
        "HOME=$OUTER_HOME" \
        "DOCKER_CONFIG=$OUTER_DOCKER_CONFIG" \
        "DOCKER_HOST=$DOCKER_HOST" \
        "TMPDIR=$OUTER_TMP" \
        "COMPOSE_DISABLE_ENV_FILE=1" \
        "$DOCKER_BIN" build \
        --file "$SNAPSHOT_DOCKERFILE" \
        --build-arg "SNAPSHOT_UID=$RUNNER_UID" \
        --build-arg "SNAPSHOT_GID=$(/usr/bin/id -g)" \
        --output "type=local,dest=$SOURCE_SNAPSHOT_ROOT" \
        "$ROOT" > "$SNAPSHOT_LOG" 2>&1; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    SOURCE_SNAPSHOT_CANONICAL=$(/usr/bin/readlink -f "$SOURCE_SNAPSHOT_ROOT") || {
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    }
    if [ -L "$SOURCE_SNAPSHOT_ROOT" ] \
        || [ ! -d "$SOURCE_SNAPSHOT_ROOT" ] \
        || [ "$SOURCE_SNAPSHOT_CANONICAL" != "$SOURCE_SNAPSHOT_ROOT" ] \
        || [ ! -f "$SOURCE_SNAPSHOT_ROOT/containers/dev/Dockerfile" ] \
        || [ ! -f "$SOURCE_SNAPSHOT_ROOT/scripts/issue20_containerized_evidence_runner.sh" ] \
        || [ -e "$SOURCE_SNAPSHOT_ROOT/.git" ] \
        || [ -e "$SOURCE_SNAPSHOT_ROOT/.formowl" ] \
        || [ -e "$SOURCE_SNAPSHOT_ROOT/.test-tmp" ] \
        || [ -e "$SOURCE_SNAPSHOT_ROOT/tests/pst-exm" ]; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    SNAPSHOT_SECRET_DIR="$SOURCE_SNAPSHOT_ROOT/deploy/connected/secrets"
    if [ -d "$SNAPSHOT_SECRET_DIR" ] \
        && [ -n "$(/usr/bin/find "$SNAPSHOT_SECRET_DIR" -mindepth 1 -maxdepth 1 ! -name README.md -print -quit)" ]; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    if ! /usr/bin/env -i \
        "PATH=$PATH" \
        "HOME=$OUTER_HOME" \
        "TMPDIR=$OUTER_TMP" \
        /usr/bin/git -c "safe.directory=$ROOT" clone \
        --local \
        --no-checkout \
        --no-hardlinks \
        "$ROOT" \
        "$GIT_SNAPSHOT_ROOT" > "$GIT_SNAPSHOT_LOG" 2>&1; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    if [ -L "$GIT_METADATA_ROOT" ] \
        || [ ! -d "$GIT_METADATA_ROOT" ] \
        || [ "$(/usr/bin/readlink -f "$GIT_METADATA_ROOT")" != "$GIT_METADATA_ROOT" ] \
        || [ "$(/usr/bin/stat -c '%u' "$GIT_METADATA_ROOT")" != "$RUNNER_UID" ] \
        || ! /usr/bin/git \
            --git-dir="$GIT_METADATA_ROOT" \
            cat-file -e '8848c69f532dbb8d412e14be1ed1c6b12a4cfc90^{commit}'; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    if ! printf 'gitdir: %s\n' "$GIT_METADATA_ROOT" > "$SOURCE_SNAPSHOT_ROOT/.git" \
        || ! /usr/bin/chmod 400 "$SOURCE_SNAPSHOT_ROOT/.git"; then
        printf '%s\n' '{"error":"runner_source_snapshot_failed","status":"error"}'
        exit 1
    fi
    if ! /usr/bin/env -i \
        "PATH=$PATH" \
        "HOME=$OUTER_HOME" \
        "DOCKER_CONFIG=$OUTER_DOCKER_CONFIG" \
        "DOCKER_HOST=$DOCKER_HOST" \
        "TMPDIR=$OUTER_TMP" \
        "COMPOSE_DISABLE_ENV_FILE=1" \
        "$DOCKER_BIN" build \
        --file "$SOURCE_SNAPSHOT_ROOT/containers/dev/Dockerfile" \
        --iidfile "$IMAGE_ID_FILE" \
        --tag formowl-dev:local \
        "$SOURCE_SNAPSHOT_ROOT" > "$BUILD_LOG" 2>&1; then
        printf '%s\n' '{"error":"runner_image_build_failed","status":"error"}'
        exit 1
    fi
    IMAGE_ID=$(/bin/cat "$IMAGE_ID_FILE") || {
        printf '%s\n' '{"error":"runner_image_id_invalid","status":"error"}'
        exit 1
    }
    if ! "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
        create-campaign-pin \
        --current-root "$ROOT" \
        --source-snapshot-root "$SOURCE_SNAPSHOT_ROOT" \
        --git-metadata-root "$GIT_METADATA_ROOT" \
        --pin-path "$CAMPAIGN_PIN" \
        --image-id "$IMAGE_ID" \
        --git-base-commit 8848c69f532dbb8d412e14be1ed1c6b12a4cfc90 \
        > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_campaign_invalid","status":"error"}'
        exit 1
    fi
    CAMPAIGN_INITIALIZING=0
fi

if ! IMAGE_ID=$(
    "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" verify-campaign \
        --current-root "$ROOT" \
        --source-snapshot-root "$SOURCE_SNAPSHOT_ROOT" \
        --git-metadata-root "$GIT_METADATA_ROOT" \
        --pin-path "$CAMPAIGN_PIN" \
        2> /dev/null
); then
    printf '%s\n' '{"error":"runner_campaign_invalid","status":"error"}'
    exit 1
fi
if [ "${#IMAGE_ID}" -ne 71 ] \
    || ! printf '%s\n' "$IMAGE_ID" | /usr/bin/grep -Eq '^sha256:[0-9a-f]{64}$' \
    || [ "$(
        "$DOCKER_BIN" image inspect --format '{{.Id}}' "$IMAGE_ID" 2> /dev/null
    )" != "$IMAGE_ID" ]; then
    printf '%s\n' '{"error":"runner_campaign_invalid","status":"error"}'
    exit 1
fi
CAMPAIGN_PIN_SHA256=$(/usr/bin/sha256sum "$CAMPAIGN_PIN")
CAMPAIGN_PIN_SHA256="sha256:${CAMPAIGN_PIN_SHA256%% *}"

case "$MODE" in
    preflight)
        set -- /bin/sh "$SCRIPT_PATH" __inside-preflight
        ;;
    operator | operator-layer | live-postgresql | lifecycle-a | lifecycle-b | lifecycle-aggregate | local-harness)
        set -- /bin/sh "$SCRIPT_PATH" \
            __inside-runner "$MODE"
        ;;
esac

AUTHORITY="$TRUST_INPUT_DIR/operator-postgresql-execution-authority.json"
AUTHORITY_PIN="$TRUST_INPUT_DIR/operator-postgresql-execution-authority-pin.json"
AUTHORITY_CANDIDATE="$HANDOFF_DIR/operator-postgresql-execution-authority.json"
AUTHORITY_PIN_CANDIDATE="$HANDOFF_DIR/operator-postgresql-execution-authority-pin.json"
OUTER_AUTHORITY_VALIDATION="$HANDOFF_DIR/outer-validation.json"
CANDIDATE_MOUNT_MODE=ro
if [ "$MODE" = "operator" ]; then
    if [ -e "$AUTHORITY" ] || [ -L "$AUTHORITY" ] \
        || [ -e "$AUTHORITY_PIN" ] || [ -L "$AUTHORITY_PIN" ] \
        || ! "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
            clear-operator-candidates \
            --candidate-dir "$HANDOFF_DIR" > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_campaign_invalid","status":"error"}'
        exit 1
    fi
    CANDIDATE_MOUNT_MODE=rw
fi

if /usr/bin/env -i \
    "PATH=$PATH" \
    "HOME=$OUTER_HOME" \
    "DOCKER_CONFIG=$OUTER_DOCKER_CONFIG" \
    "DOCKER_HOST=$DOCKER_HOST" \
    "TMPDIR=$OUTER_TMP" \
    "COMPOSE_DISABLE_ENV_FILE=1" \
    "$DOCKER_BIN" run --rm \
    --user "$(id -u):$(id -g)" \
    --group-add "$SOCKET_GID" \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --tmpfs /tmp:rw,exec,nosuid,nodev,size=256m,mode=1777 \
    --volume "$SCRATCH_ROOT:$SCRATCH_ROOT:ro" \
    --volume "$CAMPAIGN_DIR:$CAMPAIGN_DIR:ro" \
    --volume "$GIT_METADATA_ROOT:$GIT_METADATA_ROOT:ro" \
    --volume "$SOURCE_SNAPSHOT_ROOT:$ROOT:ro" \
    --volume "$REPORT_DIR:$REPORT_DIR:rw" \
    --volume "$PRIVATE_LOG_BASE:$PRIVATE_LOG_BASE:rw" \
    --volume "$INNER_LOG_DIR:$INNER_LOG_DIR:rw" \
    --volume "$HANDOFF_DIR:$HANDOFF_DIR:$CANDIDATE_MOUNT_MODE" \
    --volume "$TRUST_INPUT_DIR:$TRUST_INPUT_DIR:ro" \
    --volume "$INNER_HOME:$INNER_HOME:rw" \
    --volume "$INNER_DOCKER_CONFIG:$INNER_DOCKER_CONFIG:rw" \
    --volume "$INNER_TMP:$INNER_TMP:rw" \
    --volume /var/run/docker.sock:/var/run/docker.sock \
    --workdir "$ROOT" \
    --env "PATH=$PATH" \
    --env "DOCKER_HOST=unix:///var/run/docker.sock" \
    --env "HOME=$INNER_HOME" \
    --env "DOCKER_CONFIG=$INNER_DOCKER_CONFIG" \
    --env "COMPOSE_DISABLE_ENV_FILE=1" \
    --env "FORMOWL_RUNNER_CAMPAIGN_PIN=$CAMPAIGN_PIN" \
    --env "FORMOWL_RUNNER_CAMPAIGN_PIN_SHA256=$CAMPAIGN_PIN_SHA256" \
    --env "FORMOWL_RUNNER_DOCKER_AUTHORITY=trusted_operator_docker_daemon" \
    --env "FORMOWL_RUNNER_PRIVATE_LOG_DIR=$INNER_LOG_DIR" \
    --env "FORMOWL_RUNNER_IMAGE_ID=$IMAGE_ID" \
    --env "FORMOWL_RUNNER_SANDBOXED_UNTRUSTED_SOURCE=0" \
    --env "PYTHONPATH=$ROOT/python" \
    --env "TMPDIR=$INNER_TMP" \
    "$IMAGE_ID" \
    "$@" > "$RUN_LOG" 2>&1; then
    if [ -e "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
        || [ -L "$OPERATOR_FAILURE_DIAGNOSTIC" ] \
        || [ -e "$RUNNER_FAILURE_DIAGNOSTIC" ] \
        || [ -L "$RUNNER_FAILURE_DIAGNOSTIC" ]; then
        printf '%s\n' '{"error":"runner_command_failed","status":"error"}'
        exit 1
    fi
else
    if [ "$MODE" = "operator" ]; then
        "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
            clear-operator-candidates \
            --candidate-dir "$HANDOFF_DIR" > /dev/null 2>&1 || :
    fi
    if [ "$MODE" != "live-postgresql" ] \
        && { [ -e "$RUNNER_FAILURE_DIAGNOSTIC" ] \
            || [ -L "$RUNNER_FAILURE_DIAGNOSTIC" ]; }; then
        printf '%s\n' '{"error":"runner_command_failed","status":"error"}'
    elif [ "$MODE" = "operator" ] \
        && DIAGNOSTIC_STAGE=$(
            "$HOST_PYTHON_BIN" \
                -c "$OPERATOR_FAILURE_DIAGNOSTIC_VALIDATION_PROGRAM" \
                "$OPERATOR_FAILURE_DIAGNOSTIC" \
                "$RUNNER_UID" \
                2> /dev/null
        ); then
        printf \
            '{"error":"runner_command_failed","stage":"%s","status":"error"}\n' \
            "$DIAGNOSTIC_STAGE"
    elif [ "$MODE" = "live-postgresql" ] \
        && DIAGNOSTIC_VALUE=$(
            "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
                consume-runner-failure-diagnostic \
                --scratch-root "$SCRATCH_ROOT" \
                --private-log-dir "$PRIVATE_LOG_BASE" \
                2> /dev/null
        ); then
        DIAGNOSTIC_STAGE=${DIAGNOSTIC_VALUE%%:*}
        DIAGNOSTIC_CODE=${DIAGNOSTIC_VALUE#*:}
        printf \
            '{"error":"runner_command_failed","failure_code":"%s","stage":"%s","status":"error"}\n' \
            "$DIAGNOSTIC_CODE" \
            "$DIAGNOSTIC_STAGE"
    else
        printf '%s\n' '{"error":"runner_command_failed","status":"error"}'
    fi
    exit 1
fi

if [ "$MODE" = "operator" ]; then
    if [ -e "$OUTER_AUTHORITY_VALIDATION" ] \
        || [ -L "$OUTER_AUTHORITY_VALIDATION" ] \
        || ! /usr/bin/env -i \
            "PATH=$PATH" \
            "HOME=$OUTER_HOME" \
            "DOCKER_CONFIG=$OUTER_DOCKER_CONFIG" \
            "TMPDIR=$OUTER_TMP" \
            "COMPOSE_DISABLE_ENV_FILE=1" \
            "$DOCKER_BIN" run --rm \
            --user "$(id -u):$(id -g)" \
            --read-only \
            --cap-drop ALL \
            --security-opt no-new-privileges:true \
            --tmpfs /tmp:rw,exec,nosuid,nodev,size=64m,mode=1777 \
            --volume "$SCRATCH_ROOT:$SCRATCH_ROOT:ro" \
            --volume "$CAMPAIGN_DIR:$CAMPAIGN_DIR:ro" \
            --volume "$SOURCE_SNAPSHOT_ROOT:$ROOT:ro" \
            --volume "$REPORT_DIR:$REPORT_DIR:ro" \
            --volume "$HANDOFF_DIR:$HANDOFF_DIR:rw" \
            --workdir "$ROOT" \
            --env "PATH=$PATH" \
            --env "PYTHONPATH=$ROOT/python" \
            "$IMAGE_ID" \
            "$PYTHON_BIN" \
            "$ROOT/scripts/connected_operator_postgres_live_journey.py" \
            --validate-report "$REPORT_DIR/operator-postgresql.json" \
            --trusted-execution-authority "$AUTHORITY_CANDIDATE" \
            --trusted-execution-authority-pin "$AUTHORITY_PIN_CANDIDATE" \
            --output "$OUTER_AUTHORITY_VALIDATION" \
            > "$OUTER_LOG_DIR/operator-authority-validation.log" 2>&1 \
        || ! "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
            seal-operator-trust-inputs \
            --candidate-dir "$HANDOFF_DIR" \
            --trust-input-dir "$TRUST_INPUT_DIR" > /dev/null 2>&1 \
        || ! "$HOST_PYTHON_BIN" "$ROOT/scripts/issue20_runner_boundary.py" \
            clear-operator-candidates \
            --candidate-dir "$HANDOFF_DIR" > /dev/null 2>&1; then
        printf '%s\n' '{"error":"runner_command_failed","status":"error"}'
        exit 1
    fi
fi

rm -f "$SNAPSHOT_LOG" "$GIT_SNAPSHOT_LOG" "$BUILD_LOG" "$RUN_LOG"
printf '{"artifact_type":"issue20_containerized_evidence_runner_result_v1","docker_authority":"trusted_operator_docker_daemon","host_docker_socket_delegated":true,"mode":"%s","report_validation":"passed","sandboxed_untrusted_source":false,"status":"passed"}\n' "$MODE"
